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

class ServiceTypes(object):
    # Classes of service:
    UNRELIABLE_MESS = 0x00000001
    RELIABLE_MESS = 0x00000002
    FIFO_MESS  = 0x00000004
    CAUSAL_MESS = 0x00000008
    AGREED_MESS = 0x00000010
    SAFE_MESS  = 0x00000020

    # Message Actions
    JOIN = 0x00010000
    LEAVE = 0x020000
    KILL = 0x00040000
    SEND = 0x00000002
    SELF_DISCARD = 0x00000040 # A flag to disable refelction back of one's own message
    SEND_NOREFLECT = SEND | SELF_DISCARD

    # Message Types
    REGULAR_MESS = 0x0000003f
    REG_MEMB_MESS = 0x00001000
    TRANSITION_MESS = 0x00002000
    MEMBERSHIP_MESS = 0x00003f00

    # Membership Change Reasons
    CAUSED_BY_JOIN = 0x00000100
    CAUSED_BY_LEAVE = 0x00000200
    CAUSED_BY_DISCONNECT = 0x00000400
    CAUSED_BY_NETWORK = 0x00000800

class SpreadProto(object):
    MAX_GROUP_LEN = 32
    GROUP_FMT = '%ds' % (MAX_GROUP_LEN)
    HEADER_FMT = 'I%ssIII' % (MAX_GROUP_LEN)

    # Pre-create some format strings
    # don't send to more than MAX_GROUPS groups at once, increase if necessary
    MAX_GROUPS = 1000
    GROUP_FMTS = [ GROUP_FMT * i for i in xrange(MAX_GROUPS) ]
    # This list will consume 1000*3 = 3 KB, plus overhead.  Worth it to spend the RAM.

    # Encoded message headers
    JOIN_PKT = struct.pack('!I', ServiceTypes.JOIN)
    LEAVE_PKT = struct.pack('!I', ServiceTypes.LEAVE)
    KILL_PKT = struct.pack('!I', ServiceTypes.KILL)
    SEND_PKT = struct.pack('!I', ServiceTypes.SEND)
    SEND_SELFDISCARD_PKT = struct.pack('!I', ServiceTypes.SEND | ServiceTypes.SELF_DISCARD)

class SpreadMessage(object):
    # Classes of service:
    UNRELIABLE_MESS = 0x00000001
    RELIABLE_MESS = 0x00000002
    FIFO_MESS  = 0x00000004
    CAUSAL_MESS = 0x00000008
    AGREED_MESS = 0x00000010
    SAFE_MESS  = 0x00000020
    # A flag to disable refelction back of one's own message
    SELF_DISCARD = 0x00000040
    # Message types
    REGULAR_MESS = 0x0000003f
    REG_MEMB_MESS = 0x00001000
    TRANSITION_MESS = 0x00002000
    MEMBERSHIP_MESS = 0x00003f00
    REG_OR_TRANS_MESS = REG_MEMB_MESS | TRANSITION_MESS # optimization
    # Membership change reasons
    CAUSED_BY_JOIN = 0x00000100
    CAUSED_BY_LEAVE = 0x00000200
    CAUSED_BY_DISCONNECT = 0x00000400
    CAUSED_BY_NETWORK = 0x00000800

    def _parse_svc_type(self, svc_type):
        if svc_type & SpreadMessage.SELF_DISCARD:
            pass #print 'GOT SELF-DISCARD MARKED MESSAGE: Sender didnt want a copy of it!'
        if svc_type & SpreadMessage.REGULAR_MESS:
            #print '>> Regular Message Received message << (+)'
            # assume a regular message is never also a membership message!
            self.type_regular = True
        if svc_type & SpreadMessage.REG_MEMB_MESS:
            pass #print '>> MEMBERSHIP message << (--)'
        if self.svc_type & self.REG_OR_TRANS_MESS:
            #print '>> Some kinda membership message << (-)'
            self.type_membership = True
            if self.svc_type & self.TRANSITION_MESS:
                #print '>> TRANSITIONAL MEMBERSHIP MESSAGE <<  (A)'
                self.is_transitional = True
        if self.svc_type & self.REG_MEMB_MESS:
            #print '>> REGULAR MEMBERSHIP MESSAGE <<  (B)'
            self.is_membership = True
        if self.is_membership:
            if svc_type & self.CAUSED_BY_JOIN:
                #print '  CAUSED BY JOIN   <<<<<'
                self.cause_join = True
            if svc_type & self.CAUSED_BY_LEAVE:
                #print '  CAUSED BY LEAVE   <<<<<'
                self.cause_leave = True
            if svc_type & self.CAUSED_BY_DISCONNECT:
                #print '  CAUSED BY DISCONNECT   <<<<<'
                self.cause_disconnect = True
            if svc_type & self.CAUSED_BY_NETWORK:
                #print '  CAUSED BY NETWORK   <<<<<'
                self.cause_network = True

    def __init__(self, svc_type, mesg_type, sender, num_groups, mesg_len):
        self.svc_type = svc_type
        self.mesg_type = mesg_type
        self.sender = sender
        self.num_groups = num_groups
        self.mesg_len = mesg_len
        self.is_membership = False
        self.data = None
        self.groups = []
        #
        self.recv_time = time.time()
        # now determine various properties from svc_type
        self.type_regular = self.type_membership = self.is_transitional = False
        self.is_join = self.is_leave = False
        self.cause_network = self.cause_disconnect = self.cause_join = self.cause_leave = False
        self._parse_svc_type(svc_type)

class SpreadMessage2(object):
    def _set_data(self, data):
        self.data = data
        return self

class DataMessage(SpreadMessage2):
    def __init__(self, sender, mesg_type, self_discarded):
        SpreadMessage2.__init__(self)
        self.sender = sender
        self.mesg_type = mesg_type
        self.self_discarded = self_discarded
        self.groups = []
        self.data = None

    def _set_grps(self, groups):
        self.groups = groups
        return self

    def __repr__(self):
        return '%s:  sender:%s,  mesg_type:%d,  groups:%s,  self-disc:%s,  data:"%s"' % (self.__class__,
                            self.sender, self.mesg_type, self.groups, self.self_discarded, self.data)

class MembershipMessage(SpreadMessage2):
    def __init__(self, group):
        SpreadMessage2.__init__(self)
        self.group = group

    def _set_grps(self, groups):
        self.members = groups
        return self

    def __repr__(self):
        return '%s:  group:%s,  members:%s' % (self.__class__, self.group, self.members)

class TransitionalMessage(MembershipMessage): pass

class JoinMessage(MembershipMessage): pass

class DisconnectMessage(MembershipMessage): pass

class NetworkMessage(MembershipMessage): pass

class LeaveMessage(MembershipMessage):
    def __init__(self, group, self_leave=False):
        MembershipMessage.__init__(self, group)
        self.self_leave = self_leave
        if self_leave:
            print '!*! SELF-LEAVE DETECTED!'

    def __repr__(self):
        return '%s:  group:%s,  self_leave:%s' % (self.__class__, self.group, self.self_leave)

class SpreadMessageFactory(object):
    '''Class to determine the kind of spread message and return an object that represents
    the message we received.  It is optimized for DataMessage types.'''
    def __init__(self):
        self.this_mesg = None

    def finish_message(self):
        mesg = self.this_mesg
        self.this_mesg = None
        return mesg

    def process_groups(self, groups):
        this_mesg = self.this_mesg
        if this_mesg is None:
            return None
        this_mesg._set_grps(groups)
        return this_mesg

    def process_data(self, data):
        this_mesg = self.this_mesg
        if this_mesg is None:
            return None
        this_mesg._set_data(data)
        return this_mesg

    def process_header(self, svc_type, mesg_type, sender):
        if svc_type & ServiceTypes.REGULAR_MESS:
            # REGULAR message, we assume a regular message is never also a membership message
            self_discarded = svc_type & ServiceTypes.SELF_DISCARD != 0
            self.this_mesg = DataMessage(sender, mesg_type, self_discarded)
            return self.this_mesg
        if svc_type & ServiceTypes.REG_MEMB_MESS:
            # MEMBERSHIP messages
            if svc_type & ServiceTypes.TRANSITION_MESS:
                # TRANSITIONAL message, a type of membership message
                self.this_mesg = TransitionalMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_JOIN:
                self.this_mesg = JoinMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_LEAVE:
                self.this_mesg = LeaveMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_DISCONNECT:
                self.this_mesg = DisconnectMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_NETWORK:
                self.this_mesg = NetworkMessage(sender)
                return self.this_mesg
            # fall-thru error here, unknown cause!
            print 'ERROR: unknown membership change CAUSE.  svc_type=0x%04x' % (svc_type)
        elif svc_type & ServiceTypes.CAUSED_BY_LEAVE:
            # self-LEAVE message!
            self.this_mesg = LeaveMessage(sender, True)
            return self.this_mesg
        # fall-thru error here, unknown type
        print 'ERROR: unknown message type, neither DataMessage nor MembershipMessage marked.  svc_type=0x%04x' % (svc_type)
        self.this_mesg = None
        return None

class SpreadGroup(object):
    def __init__(self, name):
        self.name = name
        self.members = None

    def update_members(self, membership):
        '''Returns a tuple of two lists of (left, joined)'''
        pass

class SpreadListener(object):
    def receive(self, message):
        print '!-!-!  SpreadListener:  Received message:', message

    def membership(self, message):
        print '!-!-!  SpreadListener:  Received MEMBERHSIP message:', message

class AsyncSpread(asynchat.async_chat):

    def __init__(self, name, host, port,
                 cb_dropped=None,
                 cb_connected=None,
                 cb_data=None,
                 cb_membership=None,
                 listener=None,
                 membership_notifications=True,
                 priority_high=False,
                 debug=False,
                 log=None):
        '''
        Callback thoughts:
        As an end-user, I want to get a callback whenever I get a message on a certain
        group.  Also, I want to get membership change notifications as another callback.
        '''
        asynchat.async_chat.__init__(self)
        self.name = name
        self.host = host
        self.port = port
        self.membership_notifications = membership_notifications
        self.priority_high = priority_high
        self.debug = debug
        self.log = log # not yet used
        # optional args, callbacks
        self.cb_connected = cb_connected
        self.cb_dropped = cb_dropped
        self.listener = listener # general listener
        self.cb_data = cb_data
        self.cb_membership = cb_membership
        self.cb_by_group = dict() # per-group callbacks
        #
        self.private_name = None
        self.start_time = time.time()
        self.ibuffer = ''
        self.ibuffer_start = 0
        self.msg_count = 0
        #
        self.do_reflection = True # False = don't reflect my messages back to myself
        self.reflected_drops = 0
        # more settings
        self.queue_joins = []
        self.dead = False
        self.need_bytes = 0
        self.mfactory = SpreadMessageFactory()
        # group membership info here
        self.groups = dict()
        # optimizations:
        try:
            _struct_hdr = struct.Struct(SpreadProto.HEADER_FMT) # py >= 2.5 only
            self.struct_hdr = _struct_hdr.unpack
        except: # py2.4 support here
            self.struct_hdr = self._unpack_header
        # PING vars
        # IDs for mapping pings back to requests (overkill, I know)
        self.ping_callbacks = dict()
        self.ping_id = 0
        self.ping_mtype = 0xffff # set to None if you want to disable ping processing

    def start_connect(self, timeout=5):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((self.host, self.port))
        return self.wait_for_connection(timeout)

    def _unpack_header(self, payload):
        '''used for python < 2.5 where the struct module doesn't offer the
        more optimized struct.Struct class for holding pre-compiled struct formats.'''
        #print 'using self._unpack_header instread of Struct object'
        return struct.unpack(SpreadProto.HEADER_FMT, payload)

    def handle_connect(self):
        msg_connect = protocol_connect(self.name, self.membership_notifications, self.priority_high)
        self.wait_bytes(1, self.st_auth_read)
        self.push(msg_connect)

    def handle_close(self):
        print 'CONNECTION CLOSED! LOST CONNECTION TO THE SERVER!'
        self.dead = True
        self.private_name = None
        self.close()
        if self.cb_dropped is not None:
            self.cb_dropped(self)

    def loop(self, count=None, timeout=0.1, expire_every=10):
        main_loop = 0
        ping_loop = 0
        self._check_timeouts()
        while not self.dead and (count is None or main_loop < count):
            main_loop += 1
            asyncore.loop(timeout=timeout, count=1)
            if self.private_name is not None and len(self.queue_joins) > 0:
                if self.debug:
                    print 'Joining >pending< groups', self.queue_joins
                q_groups = self.queue_joins
                self.queue_joins = []
                self.join(q_groups)
            # every N iterations, check for timed out pings
            ping_loop += 1
            if expire_every and ping_loop >= expire_every:
                ping_loop = 0
                self._check_timeouts()

    def poll(self, timeout=0.001):
        if self.dead:
            raise(IOError('Connection lost to server'))
        asyncore.loop(timeout=timeout, count=1)

    def add_group_callback(self, group, cb_data, cb_membership=None):
        self.cb_by_group[group] = (cb_data, cb_membership)

    def wait_for_connection(self, timeout=10, sleep_delay=0.1):
        '''Spend time in self.poll() until the timeout expires, or we are connected, whichever first.
        Return boolean indicating if we are connected yet.  Or not.'''
        time_end = time.time() + timeout
        while not self.private_name and time.time() < time_end:
            self.poll(timeout/100)
            time.sleep(sleep_delay)
        return self.private_name is not None

    def _check_timeouts(self):
        timeouts = []
        now = time.time()
        for ping_id, cb_items in self.ping_callbacks.iteritems():
            (cb, time_sent, timeout) = cb_items
            expire = time_sent + timeout
            if now >= expire:
                if self.debug:
                    print 'EXPIRING ping id %d because now %.4f is > expire %.4f' % (ping_id, now, expire)
                timeouts.append(ping_id)
        for ping_id in timeouts:
            (cb, time_sent, timeout) = self.ping_callbacks.pop(ping_id)
            elapsed = now - time_sent
            try:
                cb(False, elapsed)
            except: pass

    def _drop(self):
        self.dead = True
        self.close()

    def _dispatch(self, message):
        listener = self.listener
        if listener is not None:
            listener.receive(message)


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
        self.set_terminator(need_bytes)

    def st_auth_read(self, data):
        #print 'STATE = ST_AUTH_READ'
        (authlen,) = struct.unpack('b', data)
        if authlen < 0:
            print 'FAILED AUTHENTICATION TO SERVER: name collision?'
            self.dead = True
            self.close()
            self.connected = False
            raise SpreadException(authlen)
        self.wait_bytes(authlen, self.st_auth_process)

    def st_auth_process(self, data):
        #print 'STATE: st_auth_process, len(data):',len(data), 'data:', data
        methods= data.rstrip().split(' ') # space delimited?
        #print 'supported auth methods:', methods
        if 'NULL' not in methods: # add 'IP' support at some point
            print 'ERROR, cannot handle non-NULL authentication: "%s"' % (data)
            self._drop()
            return
        msg_auth = struct.pack('90s', 'NULL')
        self.wait_bytes(1, self.st_read_session)
        self.push(msg_auth)
        return

    def st_read_session(self, data):
        #print 'STATE: st_read_session.'
        (accept,) = struct.unpack('b', data)
        if accept != 1:
            print 'Failed authentication / connection:', accept
            self._drop()
            raise SpreadException(accept)
        self.wait_bytes(3, self.st_read_version)

    def st_read_version(self, data):
        if self.debug:
            print 'STATE: st_read_version'
        (majorVersion, minorVersion, patchVersion) = struct.unpack('bbb', data)
        #print 'Server version: %d.%d.%d' % (majorVersion, minorVersion, patchVersion)
        version = (majorVersion | minorVersion | patchVersion)
        if version == -1: # when does this happen? does it?
            self._drop()
            raise SpreadException(version)
        self.server_version = (majorVersion, minorVersion, patchVersion)
        self.wait_bytes(1, self.st_read_private_name)

    def st_read_private_name(self, data):
        if self.debug:
            print 'STATE: st_read_private_name'
        (group_len,) = struct.unpack('b', data)
        if group_len == -1:
            self._drop()
            raise SpreadException(group_len) # TODO: FAIL
        self.wait_bytes(group_len, self.st_set_private)

    def st_set_private(self, data):
        if self.debug:
            print 'STATE: st_set_private'
        self.private_name = data
        if self.cb_connected is not None:
            self.cb_connected(self)
        self.wait_bytes(48, self.st_read_header)

    def st_read_header(self, data):
        if self.debug:
            print '\nSTATE: st_read_header'
        ENDIAN_TEST = 0x80000080
        (svc_type, sender, num_groups, mesg_type, mesg_len) = self.struct_hdr(data)
        #print 'Decoded header:',(svc_type, sender, num_groups, mesg_type, mesg_len)
        # TODO: add code to flip endianness of svc_type and mesg_type if necessary (independently?)
        endian_wrong = (svc_type & ENDIAN_TEST) == 0
        svc_type &= ~ENDIAN_TEST
        mesg_type &= ~ENDIAN_TEST
        mesg_type = mesg_type >> 8
        # and trim trailing nulls on sender
        tail_null = sender.find('\x00')
        if tail_null >= 0:
            sender = sender[0:tail_null]
        if self.debug:
            print 'Svc type: 0x%04x  sender="%s"  mesg_type: 0x%08x   num_groups: %d   mesg_len: %d' % (svc_type, sender, mesg_type, num_groups, mesg_len)
        # build up the SpreadMessage object...
        this_mesg = SpreadMessage(svc_type, mesg_type, sender, num_groups, mesg_len)
        self.this_mesg = this_mesg
        self.this_svcType = svc_type
        # pass header to message factory
        factory_mesg = self.mfactory.process_header(svc_type, mesg_type, sender)
        if this_mesg.type_membership:
            self.this_reg_message = False
            if self.debug:
                print 'MEMB>>!! sender="%s"  num_groups: %d ' % (sender, num_groups)
        else:
            # data message!
            if self.debug:
                print 'DATA>>!! svc_type:', svc_type, 'and in hex: 0x%04x' % svc_type
        if self.debug:
            print '> mesg_type = %d and hex 0x%04x' % (mesg_type, mesg_type)
            print '> sender="%s"  num_groups: %d   mesg_len:%d' % (sender, num_groups, mesg_len)
        # what if num_groups is zero?  need to handle that specially?
        if num_groups > 0:
            self.wait_bytes(num_groups * SpreadProto.MAX_GROUP_LEN, self.st_read_groups)
            return
        print 'ZERO groups for this message.  Need callback here.'
        if mesg_len > 0:
            print 'Waiting for PAYLOAD on zero-group mesg (membership notice?) payload len=%d' % (mesg_len)
            self.wait_bytes(mesg_len, self.st_read_message)
            return
        # At this point, we have a full message in factory_mesg
        self._dispatch(factory_mesg)
        self.wait_bytes(48, self.st_read_header)
        return

    def st_read_groups(self, data):
        #print 'STATE: st_read_groups'
        this_mesg = self.this_mesg
        group_packer = SpreadProto.GROUP_FMT * this_mesg.num_groups # could pre-calcualte this if necessary
        groups_padded = struct.unpack(group_packer, data)
        groups = grouplist_trim(groups_padded)
        #groups =  # trim padded nulls. use find() instead of index() to avoid exceptions.
        this_mesg.groups = groups
        mesg_len = this_mesg.mesg_len
        factory_mesg = self.mfactory.process_groups(groups)
        if self.debug:
            print 'Mesg Type:%d(0x%04x)  Mesg Len:%d  Sender: \'%s\'  Groups: %s' % (this_mesg.mesg_type, this_mesg.mesg_type, mesg_len, this_mesg.sender, groups)
        # Simple protocol: if there's a payload, read it, otherwise wait for new message
        if mesg_len > 0:
            if this_mesg.type_membership:
                self.wait_bytes(mesg_len, self.st_read_memb_change)
                return
            self.wait_bytes(mesg_len, self.st_read_message)
            return
        # this condition never happens...  hm!
        # call any callbacks here, to indicate membership changes and such
        self._dispatch(factory_mesg)
        self.wait_bytes(48, self.st_read_header)
        return

    def st_read_message(self, data):
        if self.debug:
            print 'STATE: st_read_message'
        self.msg_count += 1
        self.wait_bytes(48, self.st_read_header) # always going to a new message next
        this_mesg = self.this_mesg
        this_mesg.data = data
        factory_mesg = self.mfactory.process_data(data)
        self._dispatch(factory_mesg)
        if self.msg_count % 2000 == 0:
            print 'GOT MESSAGE %d, at %.1f msgs/second' % (self.msg_count, self.msg_count / (time.time() - self.start_time))
        print 'GOT MESSAGE (mtype:0x%04x) %d (%d bytes): ' % (this_mesg.mesg_type, self.msg_count, len(data)), data
        # Callback time
        # if the destination group is my private name, then send this back to a unicast-receiver method
        # otherwise, need to send this back to a group-based receiver
        # can have a couple of ways of doing this: explode out messages sent to multiple groups to multiple
        # callbacks?  or maybe even
        # Detect a ping to myself
        if this_mesg.sender == self.private_name:
            # message to myself!
            if this_mesg.mesg_type == self.ping_mtype:
                #print 'PING RECEIVED BACK TO MYSELF:', data
                (head, ping_id, timestamp) = data.split(':')
                ping_id = int(ping_id)
                elapsed = time.time() - float(timestamp)
                #print 'Round trip time: %.8f seconds' % ( elapsed )
                # Now, a delayed ping may have been expired! need to handle that
                if ping_id not in self.ping_callbacks:
                    print 'LATE PING ARRIVED, Elapsed:', elapsed
                    return
                else:
                    (ping_cb, send_time, timeout) = self.ping_callbacks.pop(ping_id)
                    ping_cb (True, elapsed)
                    return
            # else, this is a reflection of my own message back to me... Probably best NOT to deliver this back to myself
            # but make it configurable...
            if not self.do_reflection:
                self.reflected_drops += 1
                #print 'Reflected drops:', self.reflected_drops
                return
        # else, this is a message we need to send to a user callback
        if self.debug:
            print 'Sender = "%s"    My private name:"%s"  %d == %d' % (this_mesg.sender, self.private_name, len(this_mesg.sender), len(self.private_name))
        if self.cb_data:
            self.cb_data(this_mesg)
        for g in this_mesg.groups:
            group_cbs = self.cb_by_group.get(g, None)
            if group_cbs:
                (data_cb, memb_cb) = group_cbs
                #print 'Invoking per-group callback for group "%s"' % (g)
                data_cb(this_mesg)

    def st_read_memb_change(self, data):
        if self.debug:
            print 'STATE: st_read_memb_change():, data=', data, 'len(data)=%d' % (len(data))
            # data is notsimply decodable... sigh.  groupID?
        self.msg_count += 1
        self.wait_bytes(48, self.st_read_header) # always
        this_mesg = self.this_mesg
        group = this_mesg.sender
        factory_mesg = self.mfactory.process_data(data)
        self._dispatch(factory_mesg)
        print 'GOT Membership MESSAGE about group "%s" number %d (%d bytes): ' % (group, self.msg_count, len(data))
        # Ok, this is bad boilerplate here
        if this_mesg.cause_network:
            #if len(data) >= 24:
            #    change_fmt = '>IIIIII%ds' % (len(data) - 24)
            #    (w1, w2, w3, w4, w5, w6, who) = struct.unpack(change_fmt, data)
            #    print 'DECODED Membership info:  ',(w1, w2, w3, w4, w5, w6, who)
            #    print 'DECODED Membership info:  (0x%08x, 0x%08x, 0x%08x, 0x%08x, 0x%08x, 0x%08x, "%s")' % (w1, w2, w3, w4, w5, w6, who)
            print 'NETWORK CHANGE DETECTED'
            self.update_group_membership(group, this_mesg.groups)
        elif this_mesg.cause_join:
            # then
            print 'JOIN DETECTED:'
            self.update_group_membership(group, this_mesg.groups)
        elif this_mesg.cause_leave:
            print 'LEAVE DETECTED:'
            self.update_group_membership(group, this_mesg.groups)
        elif this_mesg.cause_disconnect:
            print 'DISCONNECT DETECTED:'
            self.update_group_membership(group, this_mesg.groups)
        if self.cb_membership is not None:
            try:
                self.cb_membership(group) # TODO: FIXME! Bad calling args. Figure them out.
            except:
                pass

    # only works after getting connected
    def join(self, groups):
        if self.private_name is None:
            print 'WARNING: no private channel name known yet from server... queueing up group join for:', groups
            self.queue_joins.extend(groups)
            return False
        send_head = protocol_create(SpreadProto.JOIN_PKT, 0, self.private_name, groups, 0)
        self.push(send_head)
        return True

    def leave(self, groups):
        send_head = protocol_create(SpreadProto.LEAVE_PKT, 0, self.private_name, groups, 0)
        self.push(send_head)
        return True

    def disconnect(self):
        who = 'tra-000255'
        #who = self.private_name
        send_head = protocol_create(SpreadProto.KILL_PKT, 0, who, [who], 0)
        self.push(send_head)
        self._drop()
        return True

    def multicast(self, groups, message, mesg_type, self_discard=True):
        '''Send a message to all members of a group.

        @param groups: group list (string)
        @type groups: list
        @param message: data payload
        @type message: string
        @param mesg_type: numeric message type, must fit in 16 bits
        @type mesg_type: int (short int)
        @param self_discard: set to True to stop server from reflecting message back to me
        @type self_discard: bool
        '''
        if self.private_name is None:
            print 'WARNING: no private channel name known yet from server... Failed message'
            return False
        #print 'multicast(groups=%s, message=%s, mesg_type=%d)' % (groups, message, mesg_type)
        data_len = len(message)
        # was SEND_PKT below.  this is good news.
        if self_discard:
            svc_type_pkt = SpreadProto.SEND_SELFDISCARD_PKT
        else:
            svc_type_pkt = SpreadProto.SEND_PKT
        header = protocol_create(svc_type_pkt, mesg_type, self.private_name, groups, data_len)
        payload = struct.pack('%ss' % data_len, message)
        pkt = ''.join((header, payload))
        self.push(pkt)
        return True

    def unicast(self, group, message, mesg_type):
        '''alias for multicasting to a single group, but disables SELF_DISCARD'''
        return self.multicast([group], message, mesg_type, self_discard=False)

    def ping(self, callback, timeout=30):
        if self.debug:
            print 'Sending PING to myself'
        payload='PING:%d:%.8f'
        this_id = self.ping_id
        self.ping_id += 1 # not thread-safe here
        payload = payload % (this_id, time.time())
        mesg_type = 0xffff
        self.ping_callbacks[this_id] = (callback, time.time(), timeout)
        self.unicast(self.private_name, payload, mesg_type)

    def update_group_membership(self, group, membership):
        print 'Update Group Membership: group "%s" now has members' % (group)
        print '  members:', membership
        if not self.groups.has_key(group):
            # new group!
            self.groups[group] = set(membership) # turn into a set()
            print 'Group Update callback needed here'
            return
        if len(membership) == 0:
            print 'SELF-LEAVE DETECTED.  Left group "%s"' % (group)
            del self.groups[group]
            print 'Group Update callback needed here'
            return
        # now compute differences
        old_members = self.groups[group]
        new_members = set(membership)
        differences = old_members ^ new_members
        self.groups[group] = new_members
        for client in differences:
            if client not in old_members:
                # then this is an add!
                print 'NEW MEMBER FOUND:', client
            else:
                # then this is a departure!
                print 'MEMBER LEFT:', client


class SpreadException(Exception):
    '''SpreadException class from pyspread code by Quinfeng.'''
    errors = {-1: 'ILLEGAL_SPREAD',
        -2: 'COULD_NOT_CONNECT',
        -3: 'REJECT_QUOTA',
        -4: 'REJECT_NO_NAME',
        -5: 'REJECT_ILLEGAL_NAME', # name too long, or bad chars
        -6: 'REJECT_NOT_UNIQUE', # name collides with another client!
        -7: 'REJECT_VERSION', # server thinks client is too old
        -8: 'CONNECTION_CLOSED',
        -9: 'REJECT_AUTH',
        -11: 'ILLEGAL_SESSION',
        -12: 'ILLEGAL_SERVICE',
        -13: 'ILLEGAL_MESSAGE',
        -14: 'ILLEGAL_GROUP',
        -15: 'BUFFER_TOO_SHORT',
        -16: 'GROUPS_TOO_SHORT',
        -17: 'MESSAGE_TOO_LONG',
        -18: 'NET_ERROR_ON_SESSION' }

    def __init__(self, errno):
        Exception.__init__(self)
        self.err_msg = SpreadException.errors.get(errno, 'unrecognized error')
        print 'SpreadException: %s' % (self.err_msg)

# Should move these into SpreadProto?
def protocol_create(svcType, mesgtype, pname, gname, data_len=0):
    #print 'protocol_Create(len(svctype)=%d, mesgtype=%s, pname=%s, gnames=%s, data_len=%d)' % (len(svcType), mesgtype, pname, gname, data_len)
    mesgtype_str = struct.pack('<I', (mesgtype & 0xffff) << 8)
    msg_hdr = struct.pack('>32sI4sI', pname, len(gname), mesgtype_str, data_len)
    grp_tag  = SpreadProto.GROUP_FMTS[len(gname)] # '32s' * len(gname)
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
    #print 'connect_fmt:', connect_fmt, 'args', (4, 1, 0, mem_opts, name_len, my_name)
    return struct.pack(connect_fmt, 4, 1, 0, mem_opts, name_len, my_name)

def grouplist_trim(groups):
    '''Trim padded nulls from list of fixed-width strings, return as new list'''
    return [ g[0:g.find('\x00')] for g in groups ]

if __name__ == '__main__':
    pass
