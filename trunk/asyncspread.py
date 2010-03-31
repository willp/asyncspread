#!/usr/bin/python
import socket, struct, copy, asyncore, asynchat, time, Queue

class SpreadMessage(object):
    UNRELIABLE_MESS = 0x00000001
    RELIABLE_MESS = 0x00000002
    FIFO_MESS  = 0x00000004
    CAUSAL_MESS = 0x00000008
    AGREED_MESS = 0x00000010
    SAFE_MESS  = 0x00000020
    REGULAR_MESS = 0x0000003f
    SELF_DISCARD = 0x00000040
    REG_MEMB_MESS = 0x00001000
    TRANSITION_MESS = 0x00002000
    CAUSED_BY_JOIN = 0x00000100
    CAUSED_BY_LEAVE = 0x00000200
    CAUSED_BY_DISCONNECT = 0x00000400
    CAUSED_BY_NETWORK = 0x00000800
    MEMBERSHIP_MESS = 0x00003f00

    CONTENT_DATA = 1
    CONTENT_OBJECT = 2
    CONTENT_DIGEST = 3

    MAX_GROUP_LEN = 32
    HEADER_FMT = 'I%ssIII' % (MAX_GROUP_LEN)


class AsyncSpread(asynchat.async_chat):
    ENDIAN_TEST = 0x80000080

    def __init__(self, name, host, port, membership_notifications=True, priority_high=False):
        asynchat.async_chat.__init__(self)
        self.name = name
        self.host = host
        self.port = port
        self.private_name = None
        self.start_time = time.time()
        self.ibuffer = ''
        self.ibuffer_start = 0
        # queue_in is for messages read FROM the socket
        self.queue_in = Queue.Queue()
        # queue_out is for data destined to go OUT the socket
        self.queue_out = Queue.Queue()
        #
        self.msg_count = 0
        self.membership_notifications = membership_notifications
        self.priority_high = priority_high
        self.queue_joins = []
        self.dead = False
        self.need_bytes = 0
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((host, port))

    def handle_connect(self):
        print 'Got connection to server!'
        msg_connect = protocol_Connect(self.name, self.priority_high)
        self.wait_bytes(1, self.st_auth_read)
        print 'STATE = ST_INIT'
        self.push(msg_connect)

    def handle_close(self):
        print 'CLOSED! LOST CONNECTION TO THE SERVER!'
        self.dead = True

    def loop(self, count=None):
        print 'entering main loop'
        main_loop = 0
        while not self.dead:
            main_loop += 1
            #print 'main loop:', main_loop
            asyncore.loop(timeout=0.1, count=1)
            if count is not None and main_loop > count:
                return
            if self.private_name is not None and len(self.queue_joins) > 0:
                print 'Joining >pending< groups', self.queue_joins
                q_groups = self.queue_joins
                self.queue_joins = []
                self.join(q_groups)

    def collect_incoming_data(self, data):
        '''Buffer the data'''
        self.ibuffer += data

    def found_terminator(self):
        data = self.ibuffer[self.ibuffer_start:(self.ibuffer_start+self.need_bytes)]
        self.ibuffer_start += self.need_bytes
        if len(self.ibuffer) > 500:
            self.ibuffer = self.ibuffer[self.ibuffer_start:]
            self.ibuffer_start = 0
        cb = self.next_state
        cb(data)

    def wait_bytes(self, need_bytes, next_state):
        self.need_bytes = need_bytes
        self.next_state = next_state
        #print '... will wait for %d bytes then will call %s' % (need_bytes, next_state)
        self.set_terminator(need_bytes)

    def st_auth_read(self, data):
        #print 'STATE = ST_AUTH_READ'
        # decide, auth NEEDED or auth IMPOSSIBLE? ???
        (authlen,) = struct.unpack('b', data)
        if authlen == -1 or authlen >= 128:
            raise SpreadException(authlen)
        self.wait_bytes(authlen, self.st_auth_process)

    def st_auth_process(self, data):
        #print 'STATE: st_auth_process'
        buffer = [ord(m) for m in data]
        sendAuthMethod = [0,]*90
        for i in xrange(4):
            sendAuthMethod[i] = buffer[i]
        msg_auth = struct.pack('!90B',*sendAuthMethod)
        self.wait_bytes(1, self.st_read_session)
        self.push(msg_auth)

    def st_read_session(self, data):
        #print 'STATE: st_read_session'
        accept = ord(data)
        if accept == -1 or accept != 1:
            raise SpreadException(accept)
        self.wait_bytes(3, self.st_read_version)

    def st_read_version(self, data):
        #print 'STATE: st_read_version'
        version_code = data
        (majorVersion, minorVersion, patchVersion) = struct.unpack('BBB', version_code)
        print 'Server version: %d.%d.%d' % (majorVersion, minorVersion, patchVersion)
        version = (majorVersion | minorVersion | patchVersion)
        if version == -1:
            raise SpreadException(version)
        self.wait_bytes(1, self.st_read_grouplen)

    def st_read_grouplen(self, data):
        #print 'STATE: st_read_grouplen'
        (group_len,) = struct.unpack('b', data)
        if group_len == -1:
            raise SpreadException(group_len)
        #print 'Private group name length is:', group_len
        self.wait_bytes(group_len, self.st_set_private)

    def st_set_private(self, data):
        #print 'STATE: st_set_private'
        self.private_name = data
        print 'My private name is:', self.private_name
        self.wait_bytes(48, self.st_read_header)

    def st_read_header(self, data):
        #print 'STATE: st_read_header'
        ENDIAN_TEST = 0x80000080
        recv_head = data
        (svcType, sender, numGroups, mesgType, mesg_len) = struct.unpack(SpreadMessage.HEADER_FMT, recv_head)
        self.this_sender = sender
        #print 'Svc type: %x  mesgType: %x' % (svcType, mesgType)
        endianWrong = (svcType & ENDIAN_TEST) == 0
        svcType &= ~ENDIAN_TEST
        #print 'Svc Type Endian wrong?:', endianWrong, 'svcType in hex = %x' % (svcType)
        if endianWrong:
            print 'Svc type: %x' % (svcType)
        reg_message = False
        if svcType & SpreadMessage.REGULAR_MESS:
            #print 'SPREAD-MESSAGE:  Regular message'
            reg_message = True
        elif svcType & SpreadMessage.REG_MEMB_MESS:
            print 'SPREAD-MESSAGE: >>>>> Membership message <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_JOIN:
                print '  CAUSED BY JOIN   <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_LEAVE:
                print '  CAUSED BY LEAVE   <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_NETWORK:
                print '  CAUSED BY NETWORK   <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_DISCONNECT:
                print '  CAUSED BY DISCONNECT   <<<<<'
        mesgType = mesgType >> 8
        self.this_svcType = svcType
        self.this_reg_message = reg_message
        self.this_mesgType = mesgType
        #print 'Hint/mesgType:', mesgType, ' and in hex = %x' % (mesgType)
        gr_left = numGroups
        # read gr_len * SpreadMessage.MAX_GROUP_LEN
        self.this_num_groups = numGroups
        self.this_mesg_len = ord(data[-4])
        self.wait_bytes(numGroups * SpreadMessage.MAX_GROUP_LEN, self.st_read_groups)

    def st_read_groups(self, data):
        #print 'STATE: st_read_groups'
        maxg = SpreadMessage.MAX_GROUP_LEN
        groups = []
        i = 0
        while self.this_num_groups > 0:
            x = data[(i*maxg):(i+1)*maxg]
            if '\x00' in x:
                x = x[0:x.index('\x00')]
            groups.append(x)
            i += 1
            self.this_num_groups -= 1
        #print 'Sender: \'%s\'   Groups: %s' % (self.this_sender, groups)
        mesg_len = self.this_mesg_len
        #print 'Message Type: %d   Message Length: %d' % (self.this_mesgType, mesg_len)
        if mesg_len > 0:
            self.wait_bytes(mesg_len, self.st_read_message)
        else:
            self.wait_bytes(48, self.st_read_header)

    def st_read_message(self, data):
        #print 'STATE: st_read_message'
        self.msg_count += 1
        if self.msg_count % 2000 == 0:
            print 'GOT MESSAGE %d, at %.1f msgs/second' % (self.msg_count, self.msg_count / (time.time() - self.start_time))
        #if self.this_reg_message:
        #    print 'GOT MESSAGE %d: ' % (self.msg_count), data
        #else:
        #    print '<No message body>'
        self.wait_bytes(48, self.st_read_header)

    # only works after getting connected
    def join(self, groups):
        if self.private_name is None:
            print 'WARNING: no private channel name known yet from server... queueing up group join for:', groups
            self.queue_joins.extend(groups)
            return
        #
        send_head = protocol_Create(ServiceTypes.JOIN_PKT, 0, self.private_name, groups)
        self.push(send_head + struct.pack('!0s',''))

    def multicast(self, groups, message, mesgtype):
        '''
        Send a message to all members of a group.
        Return the number of bytes sent

        @param groups: group list (strings)
        @param message: data payload (string)
        @param mesgtype: int (short int, 16 bits)
        '''
        data_len = len(message)
        header = protocol_Create(ServiceTypes.SEND_PKT, mesgtype, self.private_name, groups, data_len)
        payload = struct.pack('!%ss'%data_len,message)
        pkt = ''.join(header, payload)
        self.push(pkt)




class Spread(object):
    def __init__(self, sp_name='asyntest', sp_server='4803@localhost'):
        """
        Create a new Spread object.

        @param sp_name: a string specifying the name under which this client is to be
                        known; the default is a private name made up by Spread.
                        The default is test.

        @param sp_host: a string specifying the port and host of the spread daemon to use,
                        of the form "<port>@<hostname>" or "<port>", where <port> is an
                        integer port number (typically the constant DEFAULT_SPREAD_PORT)
                        represented as a string, and <hostname> specifies the host where
                        the daemon runs, typically "localhost".  The default is the
                        default Spread port and host.

        >>> sp = Spread()
        >>> sp = Spread('test','4803@localhost')
        """
        self.sp_name = sp_name
        host_list = sp_server.split('@')
        self.sp_port = int(host_list[0])
        self.sp_host = host_list[1]
        self.private_name = None

    def socket_send(self, data):
        print '>> Writing %d bytes' % (len(data))
        return self.sock.send(data)

    def socket_rec(self, want=1, timeout=None):
        got = 0
        print '<< Reading %d bytes' % (want)
        data = ''
        while got < want:
            ret = self.sock.recv(want-got)
            if len(ret) == 0:
                raise(IOError)
            data += ret
            got = len(data)
        return data

    def connect(self, priority_high=False):
        """
        Connect to the Spread daemon.
        Upon failure, SpreadException is raised.

        >>> sp.connect()
        #test#machine1
        >>> try:
        >>>     sp.connect()
        >>> except SpreadException spErr:
        >>>     print spErr.err_msg
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.sp_host,self.sp_port))
        msg_connect = protocol_Connect(self.sp_name, True, priority_high)
        self.socket_send(msg_connect)
        msg = self.socket_rec()
        (authlen,) = struct.unpack('b', msg)
        print 'AUTHLEN=', authlen
        if authlen == -1 or authlen >= 128:
            raise SpreadException(authlen)
        buffer = [ord(m) for m in self.socket_rec(authlen)]
        sendAuthMethod = [0,]*90
        for i in xrange(4):
            sendAuthMethod[i] = buffer[i]
        msg_auth = struct.pack('!90B',*sendAuthMethod)
        self.socket_send(msg_auth)
        #checkAccept
        (accept,) = struct.unpack ('b', self.socket_rec())
        if accept == -1 or accept != 1:
            print 'Authentication returned: %d' % (accept)
            raise SpreadException(accept)
        #read Version
        version_code = self.socket_rec(3)
        (majorVersion, minorVersion, patchVersion) = struct.unpack('bbb', version_code)
        print 'Server version: %d.%d.%d' % (majorVersion, minorVersion, patchVersion)
        version = (majorVersion | minorVersion | patchVersion)
        if version == -1:
            raise SpreadException(version)
        #read group
        (group_len,) = struct.unpack('b', self.socket_rec())
        if group_len < 0:
            raise SpreadException(group_len)
        print 'Group length is:', group_len
        self.private_name = self.sock.recv(group_len)
        print 'My private name is:', self.private_name
        return self.private_name


    def multicast(self, groups, message, mesgtype):
        """
        Send a message to all members of a group.
        Return the number of bytes sent

        @param groups: group list
        @param message: data

        >>> data = 'test spread multicast'
        >>> groups = ['group1']
        >>> sp.multicast(groups, message)
        21
        """
        data_len = len(message)
        #send_head = protocol_Create('SEND_MESS',self.private_name,groups,data_len)
        print '>>> using:'
        send_head = protocol_Create(ServiceTypes.SEND_PKT, mesgtype, self.private_name, groups, data_len)
        self.socket_send(send_head)
        msg = struct.pack('!%ss'%data_len,message)
        return self.socket_send(msg)


    def receive(self, timeout=None):
        """
        Block (if necessary) until a message is received, and
        return an object representing the received message.
        The return value is of type RegularMsgType
        Message Header format:
        4 bytes: serviceType
        32 bytes: sender (32=max group name length)
        4 bytes: numGroups
        4 bytes: hint/type
        4 bytes: message length

        >>> sp.receive()
        """
        recv_head = ''
        ENDIAN_TEST = 0x80000080
        while True:
            recv_head += self.socket_rec(48 - len(recv_head))
            if len(recv_head) == 48:
                break
        (svcType, sender, numGroups, mesgType, mesg_len) = struct.unpack(SpreadMessage.HEADER_FMT, recv_head)
        print 'Svc type: %x  mesgType: %x' % (svcType, mesgType)
        endianWrong = (svcType & ENDIAN_TEST) == 0
        svcType &= ~ENDIAN_TEST
        #print 'Svc Type Endian wrong?:', endianWrong, 'svcType in hex = %x' % (svcType)
        if endianWrong:
            print 'Svc type: %x' % (svcType)
        reg_message = False
        if svcType & SpreadMessage.REGULAR_MESS:
            print 'SPREAD-MESSAGE:  Regular message'
            reg_message = True
        elif svcType & SpreadMessage.REG_MEMB_MESS:
            print 'SPREAD-MESSAGE: >>>>> Membership message <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_JOIN:
                print '  CAUSED BY JOIN   <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_LEAVE:
                print '  CAUSED BY LEAVE   <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_NETWORK:
                print '  CAUSED BY NETWORK   <<<<<'
            if svcType & SpreadMessage.CAUSED_BY_DISCONNECT:
                print '  CAUSED BY DISCONNECT   <<<<<'
        mesgType = mesgType >> 8
        print 'Hint/mesgType:', mesgType, ' and in hex = %x' % (mesgType)
        gr_left = numGroups
        groups = []
        while gr_left > 0:
            x = self.socket_rec(SpreadMessage.MAX_GROUP_LEN)
            if '\x00' in x:
                x = x[0:x.index('\x00')]
            groups.append(x)
            gr_left -= 1
        print 'Sender: \'%s\'   Groups: %s' % (sender, groups)
        mesg_len = ord(recv_head[-4])
        print 'Message Type: %d   Message Length: %d' % (mesgType, mesg_len)
        message = self.socket_rec(mesg_len)
        if reg_message:
            return message
        return ''


    def join(self, groups=[]):
        """
        Join the group with the given name.  Return None.
        Upon failure, SpreadException is raised.

        @param groups: group list

        >>> sp.join(['group1','group2'])

        >>> try:
        >>>     sp.join(['group1','group2'])
        >>> except SpreadException spErr:
        >>>     print spErr.err_msg
        """
        send_head = protocol_Create(ServiceTypes.JOIN_PKT, 0, self.private_name, groups)
        self.socket_send(send_head)
        self.socket_send(struct.pack('!0s',''))


    def leave(self, groups):
        """
        leave the group with the given name.  Return None.
        Upon failure, SpreadException is raised.

        >>> sp.leave()

        >>> try:
        >>>     sp.leave()
        >>> except SpreadException spErr:
        >>>     print spErr.err_msg
        """
        send_head = protocol_Create(ServiceTypes.LEAVE_PKT, 0, self.private_name, groups)
        self.socket_send(send_head)
        self.socket_send(struct.pack('!0s',''))


    def disconnect(self):
        """
        Disconnect from the spread daemon.
        The spread object should not be used after this call.

        >>> sp.disconnect()
        """
        send_head = protocol_Create(ServiceTypes.KILL_PKT, 0, self.private_name, [self.private_name])
        self.socket_send(send_head)
        self.socket_send(struct.pack('!0s',''))
        self.sock = None
        self.private_name = None


class SpreadException(Exception):
    errors = {
        0: 'unrecognized error',
        -1: 'ILLEGAL_SPREAD',
        -2: 'COULD_NOT_CONNECT',
        -3: 'REJECT_QUOTA',
        -4: 'REJECT_NO_NAME',
        -5: 'REJECT_ILLEGAL_NAME',
        -6: 'REJECT_NOT_UNIQUE',
        -7: 'REJECT_VERSION',
        -8: 'CONNECTION_CLOSED',
        -9: 'REJECT_AUTH',
        -11: 'ILLEGAL_SESSION',
        -12: 'ILLEGAL_SERVICE',
        -13: 'ILLEGAL_MESSAGE',
        -14: 'ILLEGAL_GROUP',
        -15: 'BUFFER_TOO_SHORT',
        -16: 'GROUPS_TOO_SHORT',
        -17: 'MESSAGE_TOO_LONG',
        -18: 'NET_ERROR_ON_SESSION'
    }

    def __init__(self, errno):
        Exception.__init__(self)
        self.err_msg = SpreadException.errors.get(errno, 'unrecognized error')
        print self.err_msg

class SpreadProto(object):
    pass

class ServiceTypes(object):
    JOIN = 0x00010000
    LEAVE = 0x020000
    KILL = 0x00040000
    SEND = 0x00000002

    ENDIAN_TEST = 0x80000080

    JOIN_PKT = struct.pack('!I', JOIN)
    LEAVE_PKT = struct.pack('!I', LEAVE)
    KILL_PKT = struct.pack('!I', KILL)
    SEND_PKT = struct.pack('!I', SEND)

serviceType_dic = {
    'JOIN_MESS'  : [0,1,0,0],
    'LEAVE_MESS' : [0,2,0,0],
    'KILL_MESS'  : [0,4,0,0],
    'SEND_MESS'  : [0,0,0,2],
}
TAG = '!4B32s12B%s'
TAG2= '32s4s4s4s%s'

# must optimize this more
def protocol_Create(serType, mesgtype, pname, gname, data_len=0):
    hdr = serType
    msg_header = []
    msg_header.append(pname)

    # big endian
    msg_header.append (struct.pack('>I', len(gname)))

    # little endian
    msg_header.append (struct.pack('<I', (mesgtype & 0xffff) << 8))

    # big endian
    msg_header.append (struct.pack('>I', data_len))

    for g in gname:
        msg_header.append(g)

    tag = TAG2 % ('32s'*len(gname))
    print 'MSG_TAG:', tag
    print 'hdr = ', msg_header
    hdr += struct.pack(tag, *msg_header)
    return hdr

def protocol_Connect(connect_name, membership_notifications=True, priority_high=False):
    name_len = len(connect_name)
    mem_opts = 0x00
    if membership_notifications:
        mem_opts = mem_opts | 0x01
    if priority_high:
        mem_opts = mem_opts | 0x10
    print 'join mem opts: 0x%x' % (mem_opts)
    return struct.pack('!5B%ss' % name_len, 4, 1, 0, mem_opts, name_len, connect_name)


if __name__ == '__main__':
    pass
