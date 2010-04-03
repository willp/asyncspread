#!/usr/bin/python
import socket, struct, copy, asyncore, asynchat, time
from collections import deque

# basic API methods:
#
# Constructor: (myname, host, port)
#
# connect(want_membership_info, want_priority)
#
# join([groups])
# - joins a list of groups
#
# leave([groups])
# - leaves a list of groups
#
# multicast(message, groups[], mesg_type, svc_type)
# - send off a message to one or more groups
#
# ping(callback, timeout, payload, mesg_type, svc_type)
# - sends a message to my connections' private name and ensures it
# is received.
#
# optimized methods:
# a way to pre-generate as much of a header as possible for a given
# set of groups plus the mesgtype, maybe it's a class that produces
# byte strings (header+payload) when you pass a payload into a
# method.
#
#


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

    MAX_GROUP_LEN = 32
    HEADER_FMT = 'I%ssIII' % (MAX_GROUP_LEN)

class SpreadGroup(object):
    def __init__(self, name):
        self.name = name
        self.members = dict()


class AsyncSpread(asynchat.async_chat):

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
        # queue_out is for data destined to go OUT the socket
        self.queue_in = deque()
        self.queue_out = deque()
        # Set up per-mesgtype callbacks
        self.mesg_callbacks = [None] * (1<<16)
        # group membership info here
        self.groups = dict()
        print ' I have %d mesg_callbacks' % (len(self.mesg_callbacks))
        # optimizations:
        try:
            _struct_hdr = struct.Struct(SpreadMessage.HEADER_FMT) # py >= 2.5 only
            self.struct_hdr = _struct_hdr.unpack
        except:
            print 'using self._unpack_header instread of Struct object'
            self.struct_hdr = self._unpack_header
        #
        self.msg_count = 0
        self.membership_notifications = membership_notifications
        self.priority_high = priority_high
        self.queue_joins = []
        self.dead = False
        self.need_bytes = 0
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((host, port))

    def _unpack_header(self, payload):
        '''used for python < 2.5 where the struct module doesn't offer the
        more optimized struct.Struct class for holding pre-compiled struct formats.'''
        #print 'using self._unpack_header instread of Struct object'
        return struct.unpack(SpreadMessage.HEADER_FMT, payload)

    def handle_connect(self):
        print 'Got connection to server!'
        msg_connect = protocol_connect(self.name, self.membership_notifications, self.priority_high)
        print 'STATE = ST_INIT'
        self.wait_bytes(1, self.st_auth_read)
        self.push(msg_connect)

    def handle_close(self):
        print 'CONNECTION CLOSED! LOST CONNECTION TO THE SERVER!'
        self.dead = True
        self.close()

    def loop(self, count=None, timeout=0.1):
        print 'Entering main loop'
        main_loop = 0
        while not self.dead and (count is None or main_loop < count):
            main_loop += 1
            if count is not None:
                print 'main loop:', main_loop
            asyncore.loop(timeout=timeout, count=1)
            if self.private_name is not None and len(self.queue_joins) > 0:
                print 'Joining >pending< groups', self.queue_joins
                q_groups = self.queue_joins
                self.queue_joins = []
                self.join(q_groups)

    def poll(self, timeout=0.001):
        if self.dead:
            raise(IOError('Connection lost to server'))
        #print 'doing IO poll'
        asyncore.loop(timeout=timeout, count=1)

    def wait_for_connection(self, timeout=10):
        time_end = time.time() + timeout
        while not self.private_name and time.time() < time_end:
            self.poll(timeout/100)
            time.sleep(0.1)
        return self.private_name is not None

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
        need_bytes = int(need_bytes) # py 2.4 fixup for struct.unpack()'s longs not satisfying isinstance(int)
        self.need_bytes = need_bytes
        self.next_state = next_state
        #print '... will wait for %d bytes then will call %s' % (need_bytes, next_state)
        self.set_terminator(need_bytes)

    def st_auth_read(self, data):
        print 'STATE = ST_AUTH_READ'
        # decide, auth NEEDED or auth IMPOSSIBLE? ???
        (authlen,) = struct.unpack('b', data)
        if authlen == -1 or authlen >= 128:
            print 'FAILED AUTHENTICATION TO SERVER: name collision?'
            self.connected = False
            raise SpreadException(authlen)
        self.wait_bytes(authlen, self.st_auth_process)

    def st_auth_process(self, data):
        print 'STATE: st_auth_process, len(data):'#,len(data)
        #buffer = struct.unpack('B', data) # buffer = [ord(m) for m in data]
        buffer = [ord(m) for m in data]
        sendAuthMethod = [0,]*90
        for i in xrange(4):
            sendAuthMethod[i] = buffer[i]
        msg_auth = struct.pack('!90B',*sendAuthMethod)
        self.wait_bytes(1, self.st_read_session)
        self.push(msg_auth)

    def st_read_session(self, data):
        print 'STATE: st_read_session'
        accept = ord(data)
        if accept == -1 or accept != 1:
            raise SpreadException(accept)
        self.wait_bytes(3, self.st_read_version)

    def st_read_version(self, data):
        print 'STATE: st_read_version'
        version_code = data
        (majorVersion, minorVersion, patchVersion) = struct.unpack('BBB', version_code)
        print 'Server version: %d.%d.%d' % (majorVersion, minorVersion, patchVersion)
        version = (majorVersion | minorVersion | patchVersion)
        if version == -1:
            raise SpreadException(version)
        self.wait_bytes(1, self.st_read_grouplen)

    def st_read_grouplen(self, data):
        print 'STATE: st_read_grouplen'
        (group_len,) = struct.unpack('b', data)
        if group_len == -1:
            raise SpreadException(group_len)
        #print 'Private group name length is:', group_len
        self.wait_bytes(group_len, self.st_set_private)

    def st_set_private(self, data):
        print 'STATE: st_set_private'
        self.private_name = data
        print 'My private name is:', self.private_name
        self.wait_bytes(48, self.st_read_header)

    def st_read_header(self, data):
        #print 'STATE: st_read_header'
        ENDIAN_TEST = 0x80000080
        recv_head = data
        (svc_type, sender, num_groups, mesg_type, mesg_len) = self.struct_hdr(recv_head)
        #(svc_type, sender, num_groups, mesg_type, mesg_len) = struct.unpack(SpreadMessage.HEADER_FMT, data)
        #print 'unpacked header',(svc_type, sender, num_groups, mesg_type, mesg_len)
        self.this_sender = sender
        endian_wrong = (svc_type & ENDIAN_TEST) == 0
        svc_type &= ~ENDIAN_TEST
        mesg_type &= ~ENDIAN_TEST
        print 'Svc type: 0x%04x  mesg_type: 0x%08x' % (svc_type, mesg_type)
        self.this_svcType = svc_type
        mesg_type = mesg_type >> 8
        self.this_mesgType = mesg_type
        self.this_mesg_num_groups = num_groups
        self.this_mesg_len = mesg_len
        #print 'Svc Type Endian wrong?:', endianWrong, 'svc_type in hex = 0x%04x' % (svc_type)
        if endian_wrong:
            print 'Svc type endianness-corrected: 0x%04x' % (svc_type)
        if svc_type & SpreadMessage.REGULAR_MESS:
            self.this_reg_message = True
            print '!! Regular message!  svc_type = 0x%04x' % (svc_type)
        if svc_type & SpreadMessage.TRANSITION_MESS:
            print '>> TRANSITIONAL MEMBERSHIP MESSAGE <<  (A)'
        if svc_type & SpreadMessage.REG_MEMB_MESS:
            print '>> REGULAR MEMBERSHIP MESSAGE <<  (B)'
        if True:#elif svc_type & SpreadMessage.REG_MEMB_MESS:
            self.this_reg_message = False
            #print 'SPREAD-MESSAGE: >>>>> Membership message <<<<<'
            if svc_type & SpreadMessage.CAUSED_BY_JOIN:
                print '  CAUSED BY JOIN   <<<<<'
                print '>>!! sender="%s"  num_groups: %d ' % (sender, num_groups)
                print 'I got joined to group %s which has some members...' % (sender)
            if svc_type & SpreadMessage.CAUSED_BY_LEAVE:
                print '  CAUSED BY LEAVE   <<<<<'
            if svc_type & SpreadMessage.CAUSED_BY_NETWORK:
                print '  CAUSED BY NETWORK   <<<<<'
            if svc_type & SpreadMessage.CAUSED_BY_DISCONNECT:
                print '  CAUSED BY DISCONNECT   <<<<<'
        else:
            # unknown message type, interesting.
            print '>>!! unknown message type, interesting:', svc_type, 'and in hex: 0x%04x' % svc_type
        print '> mesg_type = %d and hex 0x%04x' % (mesg_type, mesg_type)
        print '> sender="%s"  num_groups: %d ' % (sender, num_groups)
        # what if num_groups is zero?  need to handle that specially?
        if num_groups > 0:
            #print 'reading %d groups ahead' % (num_groups)
            self.wait_bytes(num_groups * SpreadMessage.MAX_GROUP_LEN, self.st_read_groups)
        else:
            print 'ZERO groups for this message.  Need callback here.'
            if mesg_len > 0:
                print 'Waiting for PAYLOAD on zero-group mesg (membership notice?) payload len=%d' % (mesg_len)
                self.wait_bytes(mesg_len, self.st_read_message)
            else:
                self.wait_bytes(48, self.st_read_header)

    def st_read_groups(self, data):
        #print 'STATE: st_read_groups'
        group_field = '%ds' % SpreadMessage.MAX_GROUP_LEN
        group_packer = group_field * self.this_mesg_num_groups
        groups_padded = struct.unpack(group_packer, data)
        groups = [ g[0:g.index('\x00')] for g in groups_padded ] # trim padded nulls
        self.this_mesg_groups = groups
        mesg_len = self.this_mesg_len
        print 'Mesg Type:%d(0x%04x)  Mesg Len:%d  Sender: \'%s\'  Groups: %s' % (self.this_mesgType, self.this_mesgType, mesg_len, self.this_sender, groups)
        # Simple protocol: if there's a payload, read it, otherwise wait for new message
        if mesg_len > 0:
            self.wait_bytes(mesg_len, self.st_read_message)
        else:
            # call any callbacks here, to indicate membership changes and such
            print 'NEED CALLBACK HERE'
            self.wait_bytes(48, self.st_read_header)

    def st_read_message(self, data):
        #print 'STATE: st_read_message'
        self.msg_count += 1
        if self.msg_count % 2000 == 0:
            print 'GOT MESSAGE %d, at %.1f msgs/second' % (self.msg_count, self.msg_count / (time.time() - self.start_time))
        #if self.this_reg_message:
        print 'GOT MESSAGE %d (%d bytes): ' % (self.msg_count, len(data)), data
        #else:
        #    print '<No message body>'
        print ''
        self.wait_bytes(48, self.st_read_header)

    # only works after getting connected
    def join(self, groups):
        if self.private_name is None:
            print 'WARNING: no private channel name known yet from server... queueing up group join for:', groups
            self.queue_joins.extend(groups)
            return
        #
        send_head = protocol_create(ServiceTypes.JOIN_PKT, 0, self.private_name, groups, 0)
        self.push(send_head)

    def leave(self, groups):
        send_head = protocol_create(ServiceTypes.LEAVE_PKT, 0, self.private_name, groups, 0)
        self.push(send_head)

    def disconnect(self):
        send_head = protocol_create(ServiceTypes.KILL_PKT, 0, self.private_name, [self.private_name], 0)
        self.push(send_head)
        self.dead = True
        self.close()
        print 'Disconnected!'
        #self.sock = None
        #self.private_name = None

    def multicast(self, groups, message, mesg_type):
        '''
        Send a message to all members of a group.
        Return the number of bytes sent

        @param groups: group list (strings)
        @param message: data payload (string)
        @param mesg_type: int (short int, 16 bits)
        '''
        if self.private_name is None:
            print 'WARNING: no private channel name known yet from server... Failed MULTICAST message'
            return False
        #print 'multicast(groups=%s, message=%s, mesg_type=%d)' % (groups, message, mesg_type)
        data_len = len(message)
        header = protocol_create(ServiceTypes.SEND_PKT, mesg_type, self.private_name, groups, data_len)
        payload = struct.pack('%ss' % data_len, message)
        pkt = ''.join((header, payload))
        self.push(pkt)
        return True

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

class ServiceTypes(object):
    JOIN = 0x00010000
    LEAVE = 0x020000
    KILL = 0x00040000
    SEND = 0x00000002

    JOIN_PKT = struct.pack('!I', JOIN)
    LEAVE_PKT = struct.pack('!I', LEAVE)
    KILL_PKT = struct.pack('!I', KILL)
    SEND_PKT = struct.pack('!I', SEND)


def make_header_fmt(num_groups):
    pack_str = '>32sI4sI' + ('32s' * num_groups)
    return pack_str

# must optimize this more
def protocol_create(svcType, mesgtype, pname, gname, data_len=0):
    #print 'protocol_Create(len(svctype)=%d, mesgtype=%s, pname=%s, gnames=%s, data_len=%d)' % (len(svcType), mesgtype, pname, gname, data_len)
    mesgtype_str = struct.pack('<I', (mesgtype & 0xffff) << 8)
    msg_hdr = struct.pack('>32sI4sI', pname, len(gname), mesgtype_str,data_len)
    grp_tag  = '32s' * len(gname)
    grp_hdr = struct.pack(grp_tag, *gname)
    hdr = ''.join((svcType, msg_hdr, grp_hdr))
    return hdr

def protocol_connect(my_name, membership_notifications=True, priority_high=False):
    name_len = len(my_name)
    mem_opts = 0x00
    if membership_notifications:
        mem_opts |= 0x01
    if priority_high:
        mem_opts |= 0x10
    connect_fmt = '!5B%ds' % name_len
    print 'connect_fmt:', connect_fmt, 'args', (4, 1, 0, mem_opts, name_len, my_name)
    return struct.pack(connect_fmt, 4, 1, 0, mem_opts, name_len, my_name)


if __name__ == '__main__':
    pass
