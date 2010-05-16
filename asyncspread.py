#!/usr/bin/python
import socket, struct, copy, asyncore, asynchat, time, logging, sys, threading
from collections import deque

# This code is released for use under the Gnu Public License V3 (GPLv3).
#
# Thanks to Qingfeng for the initial version of code that inspired this rewrite.
#
# Thanks to Spread Concepts, LLC., especially Amir Yair and Jonathan Stanton for
# the Spread toolkit.
#
# Please accept my humble apologies for this code being somewhat disorganized.
# It is a work in progress!
#
# Author:  "J. Will Pierce" <willp@nuclei.com>

class NullLogHandler(logging.Handler):
    '''Log null handler for polite logging'''
    def emit(self, record): pass
logging.getLogger().addHandler(NullLogHandler())

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

    SEND = SAFE_MESS
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
    # Don't send to more than MAX_GROUPS groups at once, increase if necessary
    MAX_GROUPS = 1000
    # This list will consume 1000*3 = 3 KB, plus overhead.  Worth it to spend the RAM.
    GROUP_FMTS = [ GROUP_FMT * i for i in xrange(MAX_GROUPS) ]

    # Encoded message headers
    JOIN_PKT = struct.pack('!I', ServiceTypes.JOIN)
    LEAVE_PKT = struct.pack('!I', ServiceTypes.LEAVE)
    KILL_PKT = struct.pack('!I', ServiceTypes.KILL)
    SEND_PKT = struct.pack('!I', ServiceTypes.SEND)
    SEND_SELFDISCARD_PKT = struct.pack('!I', ServiceTypes.SEND | ServiceTypes.SELF_DISCARD)

    # Handshake message parts
    AUTH_PKT = struct.pack('90s', 'NULL')

    def __init__(self):
        self.set_level()
    
    def set_level(self, default_type=ServiceTypes.SAFE_MESS):
        self.default_type = default_type
        self.send_pkt = struct.pack('!I', default_type)
        self.send_pkt_selfdisc = struct.pack('!I', default_type | ServiceTypes.SELF_DISCARD)

    @staticmethod
    def protocol_create(svcType, mesgtype, pname, gname, data_len=0):
        #print 'protocol_Create(len(svctype)=%d, mesgtype=%s, pname=%s, gnames=%s, data_len=%d)' % (len(svcType), mesgtype, pname, gname, data_len)
        mesgtype_str = struct.pack('<I', (mesgtype & 0xffff) << 8)
        msg_hdr = struct.pack('>32sI4sI', pname, len(gname), mesgtype_str, data_len)
        grp_tag  = SpreadProto.GROUP_FMTS[len(gname)] # '32s' * len(gname)
        grp_hdr = struct.pack(grp_tag, *gname)
        hdr = ''.join((svcType, msg_hdr, grp_hdr))
        return hdr

    @staticmethod
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

class SpreadMessage(object):
    def _set_data(self, data):
        self.data = data
        return self

class DataMessage(SpreadMessage):
    def __init__(self, sender, mesg_type, self_discarded):
        SpreadMessage.__init__(self)
        self.sender = sender
        self.mesg_type = mesg_type
        self.self_discarded = self_discarded
        self.groups = []
        self.data = None # TODO: empty string may be a better choice here

    def _set_grps(self, groups):
        self.groups = groups
        return self

    def __repr__(self):
        return '%s:  sender:%s,  mesg_type:%d,  groups:%s,  self-disc:%s,  data:"%s"' % (self.__class__,
                            self.sender, self.mesg_type, self.groups, self.self_discarded, self.data)

class MembershipMessage(SpreadMessage):
    def __init__(self, group):
        SpreadMessage.__init__(self)
        self.group = group
        self.members = []

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

    def __repr__(self):
        return '%s:  group:%s,  self_leave:%s' % (self.__class__, self.group, self.self_leave)

class SpreadMessageFactory(object):
    '''Class to determine the kind of spread message and return an object that represents
    the message we received.  It is optimized for DataMessage types.'''
    def __init__(self):
        self._reset()

    def _reset(self):
        self.this_mesg = None
        self.num_groups = 0
        self.mesg_len = 0

    def finish_message(self):
        mesg = self.this_mesg
        self._reset()
        return mesg

    def process_groups(self, groups):
        this_mesg = self.this_mesg
        assert this_mesg is not None, 'Message Factory invoked out of order.'
        this_mesg._set_grps(groups)
        return this_mesg

    def process_data(self, data):
        this_mesg = self.this_mesg
        assert this_mesg is not None, 'Message Factory invoked out of order.'
        this_mesg._set_data(data)
        return this_mesg

    def process_header(self, svc_type, mesg_type, sender, num_groups, mesg_len):
        self.num_groups = num_groups
        self.mesg_len = mesg_len
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
        # strange, sometimes this is received NOT as a regular membership message
        if svc_type & ServiceTypes.TRANSITION_MESS:
            # TRANSITIONAL message, a type of membership message
            self.this_mesg = TransitionalMessage(sender)
            return self.this_mesg
        # fall-thru error here, unknown type
        print 'ERROR: unknown message type, neither DataMessage nor MembershipMessage marked.  svc_type=0x%04x' % (svc_type)
        self.this_mesg = None
        return None


class SpreadListener(object):
    def __init__(self):
        self.groups = dict()

    def _process_membership(self, conn, message):
        '''Do not over-ride this method unless you plan on implementing an alternate
        mechanism for tracking group membership changes.  In which case, you must also
        over-ride update_group_membership()'''
        # regardless of message type (join/leave/disconnect/network), calculate membership changes
        self.update_group_membership(conn, message)

    def update_group_membership(self, conn, message):
        group = message.group
        if isinstance(message, TransitionalMessage):
            self.handle_group_trans(conn, group)
            return
        new_membership = set(message.members)
        # new group!
        if not self.groups.has_key(group):
            self.groups[group] = new_membership
            self.handle_group_start(conn, group, new_membership)
            return
        old_membership = self.groups[group]
        if (isinstance(message, LeaveMessage) and message.self_leave) or len(new_membership) == 0:
            del self.groups[group]
            self.handle_group_end(conn, group, old_membership)
            return
        # now compute differences
        differences = old_membership ^ new_membership # symmetric difference
        self.groups[group] = new_membership
        cause = type(message)
        # notify if we have a network split event
        if isinstance(message, NetworkMessage):
            changes = len(new_membership) - len(old_membership)
            self.handle_network_split(conn, group, changes, old_membership, new_membership)
        for member in differences:
            if member not in old_membership:
                # this is an add
                self.handle_group_join(conn, group, member, cause)
            else:
                # this is a leave/departure
                self.handle_group_leave(conn, group, member, cause)

    def get_group_members(self, group):
        return self.groups[group]

    # this method is called once every so often by the "main loop" of AsyncSpread
    def _process_timer(self, conn):
        self.handle_timer(conn)

    def handle_timer(self, conn):
        '''override this to have your listener invoked once in a while (configurable?) to do maintenance'''
        pass

    # a series of _process* methods that in just call their respective (overriden?) handle_* versions
    # these are here to make it easier for subclasses to override handle_* and permit
    # future enhancements to the base class, similar to how _process_membership() does
    # bookkeeping, before calling handle_*() methods

    def _process_data(self, conn, message):
        # not sure if this method is really needed...
        self.handle_data(conn, message)

    def _process_connected(self, conn):
        self.handle_connected(conn)

    def _process_authenticated(self, conn):
        self.handle_authenticated(conn)

    def _process_error(self, conn, exc):
        self.handle_error(conn, exc)

    def _process_dropped(self, conn):
        self.handle_dropped(conn)

    def handle_connected(self, conn):
        pass

    def handle_authenticated(self, conn):
        pass

    def handle_error(self, conn, exc):
        pass

    def handle_dropped(self, conn):
        pass

    def handle_data(self, conn, message):
        pass

    def handle_group_start(self, conn, group, membership):
        pass

    def handle_group_trans(self, conn, group):
        pass

    def handle_group_end(self, conn, group, old_membership):
        pass

    def handle_group_join(self, conn, group, member, cause):
        pass

    def handle_group_leave(self, conn, group, member, cause):
        pass

    def handle_network_split(self, conn, group, changes, old_membership, new_membership):
        pass

class SpreadPingListener(SpreadListener):
    ping_mtype = 0xffff # change if necessary

    def __init__(self, check_interval=1):
        SpreadListener.__init__(self)
        # PING vars
        # IDs for mapping pings back to requests (overkill, I know)
        self.ping_callbacks = dict()
        self.ping_id = 0
        # counters
        self.ping_sent = 0
        self.ping_recv = 0
        self.ping_late = 0

    def _process_data(self, conn, message):
        data = message.data
        if message.mesg_type == self.ping_mtype and message.sender == conn.private_name and data is not None: # change to empty string for default empty data?
            (head, ping_id, timestamp) = data.split(':')
            ping_id = int(ping_id)
            elapsed = time.time() - float(timestamp)
            # pings expire, handle late arrivals here
            if ping_id not in self.ping_callbacks:
                self.ping_late += 1
                return
            (ping_cb, send_time, timeout) = self.ping_callbacks.pop(ping_id)
            self.ping_recv += 1
            ping_cb (True, elapsed)
            return
        self.handle_data(conn, message)

    def handle_timer(self, conn):
        '''moved check_timeouts() here'''
        pending_pings = len(self.ping_callbacks)
        if pending_pings == 0:
            return
        timeouts = []
        now = time.time()
        for ping_id, cb_items in self.ping_callbacks.iteritems():
            (cb, time_sent, timeout) = cb_items
            expire = time_sent + timeout
            if now >= expire:
                #print 'EXPIRING ping id %d because now %.4f is > expire %.4f' % (ping_id, now, expire)
                timeouts.append(ping_id)
        for ping_id in timeouts:
            (user_cb, time_sent, timeout) = self.ping_callbacks.pop(ping_id)
            elapsed = now - time_sent
            try:
                user_cb(False, elapsed)
            except: pass

    def ping(self, conn, callback, timeout=30):
        payload = 'PING:%d:%.8f'
        this_id = self.ping_id
        self.ping_id += 1 # not thread-safe here
        payload = payload % (this_id, time.time())
        mesg_type = self.ping_mtype
        self.ping_callbacks[this_id] = (callback, time.time(), timeout)
        self.ping_sent += 1
        conn.unicast(conn.private_name, payload, mesg_type)

class GroupCallback(object):
    '''Container class for callbacks about a group.'''
    def __init__(self,
                 cb_data=None,
                 cb_join=None,
                 cb_leave=None,
                 cb_network=None,
                 cb_start=None,
                 cb_end=None):
        self.cb_data = cb_data
        self.cb_join = cb_join
        self.cb_leave = cb_leave
        self.cb_network = cb_network
        self.cb_start = cb_start
        self.cb_end = cb_end

class CallbackListener(SpreadListener):
    '''A helper class for registering callbacks that are invoked on various events, and
    permits a user to build an application without using any inheritance at all.  May fit
    some applications better than other listeners.

    May need to handle user exceptions specially in the handle_ methods...

    There is some risk of this code being very boilerplate.  Oh well.  It's helper code.
    '''
    def __init__(self, cb_auth=None, cb_data=None, cb_dropped=None, cb_error=None):
        '''Creates a new callback listener.

        @param auth: callback to be invoked as auth(listener, conn) when the session passes authenticated and the session is 'connected'
        @param data: callback to be invoked as data(listener, conn, message) when any data message arrives on any group
        @param dropped: callback to be invoked as dropped(listener, conn) when the connection is dropped
        @param error: callback to be invoked as error(listener, conn, exception) when an error happens
        '''
        SpreadListener.__init__(self)
        self.cb_auth = cb_auth
        self.cb_data = cb_data
        self.cb_dropped = cb_dropped
        self.cb_error = cb_error
        self.cb_groups = dict()

    def set_group_cb(self, group, group_callback):
        '''Only permit one GroupCallback object per group.  However, a message will be sent to multiple
        group callbacks if the message is delivered to multiple groups, and those groups are set up with
        callback objects.
        
        @param group: the name of the group for this callback
        @type group: string
        @param group_callback: the GroupCallback object containing the callbacks for this group
        @type group_callback: GroupCallback
        '''
        self.cb_groups[group] = group_callback

    def handle_authenticated(self, conn):
        if self.cb_auth:
            self.cb_auth(self, conn)

    def handle_dropped(self, conn):
        if self.cb_dropped:
            self.cb_dropped(self, conn)

    def handle_error(self, conn, exc):
        if self.cb_error:
            self.cb_error(self, conn, exc)

    # this function avoids a lot of boilerplate here, should also catch exceptions perhaps
    def _invoke_cb(self, group, callback, args):
        gcb = self.cb_groups.get(group, None)
        if gcb:
            cb_ref = getattr(gcb, callback)
            if cb_ref:
                try:
                    cb_ref(*args)
                except:
                    print 'Exception in client callback'

    def handle_data(self, conn, message):
        if self.cb_data:
            self.cb_data(self, conn, message)
        groups = message.groups
        for group in groups:
            self._invoke_cb(group, 'cb_data', (conn, message))

    def handle_group_start(self, conn, group, membership):
        self._invoke_cb(group, 'cb_start', (conn, group, membership))

    def handle_group_end(self, conn, group, old_membership):
        self._invoke_cb(group, 'cb_end', (conn, group, old_membership))

    def handle_group_join(self, conn, group, member, cause):
        self._invoke_cb(group, 'cb_join', (conn, group, member, cause))

    def handle_group_leave(self, conn, group, member, cause):
        self._invoke_cb(group, 'cb_leave', (conn, group, member, cause))

    def handle_network_split(self, conn, group, changes, old_membership, new_membership):
        self._invoke_cb(group, 'cb_network', (group, changes, old_membership, new_membership))


class DebugListener(SpreadListener):
    '''super verbose'''

    def handle_connected(self, conn):
        print 'DEBUG: Got connected!'

    def handle_dropped(self, conn):
        print 'DEBUG: Lost connection!'

    def handle_authenticated(self, conn):
        print 'DEBUG: Got authenticated, new session is ready!'

    def handle_error(self, conn, exc):
        print 'DEBUG: Got error! Exception:', type(exc), exc

    def handle_data(self, conn, message):
        print 'DEBUG: Received message:', message

    def handle_group_start(self, conn, group, membership):
        print 'DEBUG: New Group Joined', group, 'members:', membership

    def handle_group_trans(self, conn, group):
        print 'DEBUG: Transitional message received, not much actionable here. Group:', group

    def handle_group_end(self, conn, group, old_membership):
        print 'DEBUG: Group no longer joined:', group, 'Old membership:', old_membership

    def handle_group_join(self, conn, group, member, cause):
        print 'DEBUG: Group Member Joined group:', group, 'Member:', member, 'Cause:', cause

    def handle_group_leave(self, conn, group, member, cause):
        print 'DEBUG: Group Member Left group:', group, 'Member:', member, 'Cause:', cause

    def handle_network_split(self, conn, group, changes, old_membership, new_membership):
        print 'DEBUG: Network Split event, group:', group, 'Number changes:', changes, 'Old Members:', old_membership, 'New members:', new_membership

    def handle_timer(self, conn):
        print 'DEBUG: Timer tick...'
        # now invoke any parent class handle_timer() method too
        try:
            super(DebugListener, self).handle_timer(conn)
        except:
            pass
            print 'DEBUG: Parent class threw an exception in handle_timer()'

class AsyncSpread(asynchat.async_chat):
    '''Asynchronous client API for Spread 4.x group messaging.'''
    def __init__(self, name, host, port,
                 listener=None,
                 membership_notifications=True,
                 priority_high=False, 
                 keepalive=True):
        '''Create object representing asynchronous connection to a spread daemon.

        TODO: Add keepalive socket support!

        @param name: your unique self-identifier, no more than 10 characters long, unique to this server
        @type name: str
        @param host: Spread server hostname (fully qualified domain name)
        @type host: str
        @param port: TCP port number for spread daemon
        @type port: int
        @param membership_notifications: tells Spread to provide group membership (presence) notifications, leave True for most uses
        @type membership_notifications: bool
        @param priority_high: undocumented boolean for Spread session protocol. Does not speed anything up if set to True.
        @type priority_high: bool
        '''
        asynchat.async_chat.__init__(self)
        self.name, self.host, self.port = name, host, port
        self.membership_notifications = membership_notifications
        self.priority_high = priority_high
        self.listener = listener # a SpreadListener
        self.keepalive = keepalive
        self.keepalive_idle = 10
        self.keepalive_maxdrop = 6 # one minute
        # initialize some basics
        self.logger = logging.getLogger()
        self.proto = SpreadProto()
        self.private_name = None
        self.ibuffer = ''
        self.ibuffer_start = 0
        self.msg_count = 0
        # more settings
        self.queue_joins = []
        self.dead = False
        self.need_bytes = 0
        self.mfactory = None
        self.io_active = False
        self.io_ready = threading.Event()
        self.do_reconnect = False
        self.out_queue = deque() # outbound messages for threaded uses
        # optimization for python 2.5+
        try:
            _struct_hdr = struct.Struct(SpreadProto.HEADER_FMT) # precompiled
            self.struct_hdr = _struct_hdr.unpack # bound method
        except: # python <= 2.4 support
            self.struct_hdr = self._unpack_header

    def _do_connect(self):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.keepalive:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) # enable            
                self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, self.keepalive_idle)
                self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, self.keepalive_idle)
                self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, self.keepalive_maxdrop)
            except:
                self.logger.info('Failed setting TCP KEEPALVIE on socket. Firewall issues may cause connection to silently become a black hole.')
                self.keepalive = False
        self.dead = False
        self.connect((self.host, self.port))

    def start_connect(self, timeout=10):
        self.mfactory = SpreadMessageFactory()
        self._do_connect()
        print 'waiting for connection...'
        return self.wait_for_connection(timeout)

    def set_level(self, level):
        '''totally delegated to internal SpreadProto object'''
        self.proto.set_level(level)

    def _unpack_header(self, payload):
        '''used for python < 2.5 where the struct module doesn't offer the
        more optimized struct.Struct class for holding pre-compiled struct formats.'''
        return struct.unpack(SpreadProto.HEADER_FMT, payload)

    def handle_connect(self):
        print 'handle_connect(): my name is:', self.name
        msg_connect = SpreadProto.protocol_connect(self.name, self.membership_notifications, self.priority_high)
        self.wait_bytes(1, self.st_auth_read)
        self.push(msg_connect)
        self.listener._process_connected(self) # dubious utility here

    def handle_close(self):
        self.logger.info('Connection lost to server: %s:%d' % (self.host, self.port))
        self.dead = True
        self.private_name = None
        self.mfactory = None
        self.close()
        self.listener._process_dropped(self)

    def handle_error(self):
        (exc_type, exc_val, tb) = sys.exc_info()
        self.logger.debug ('handle_error(): Got exception: %s' % exc_val)
        self._drop()
        sys.exc_clear()
        self.listener._process_error(self, exc_val)
        self.listener._process_dropped(self)

    def start_io_thread(self, forever=False):
        if self.io_active: # not thread safe, not really. race condition here.
            return
        thr = threading.Thread(target=self.do_io, args=(forever,), name='AsyncSpread I/O Thread')
        thr.daemon=True
        thr.start()

    def do_io(self, forever=False, timer_interval=1):
        self.io_active = True
        main_loop = 0
        if self.dead:
            # wait
            print 'self.DEAD in IO thread...'
        timer_next = time.time() + timer_interval
        while not self.dead or forever:
            main_loop += 1
            # spend some time in asyncore event loop
            if not self.dead:
                asyncore.loop(timeout=0.01, count=50, use_poll=True)
            # then do some timer tasks
            if time.time() >= timer_next:
                self.listener._process_timer(self)
                timer_next = time.time() + timer_interval
            # then do a reconnect if requested
            if self.dead and self.do_reconnect:
                self.do_reconnect = False # reset flag
                print 'IO thread trying to start_connect()...'
                self.start_connect()
            # make sure not to deliver any messages if the session isn't ready
            if not self.io_ready.isSet():
                print 'IO not ready!'
                continue
            # deliver queued up outbound data
            while len(self.out_queue) > 0 and not self.dead and self.private_name is not None:
                print 'QUEUE-LENGTH:', len(self.out_queue)
                print '(IO SEND) writing to socket...'
                self.push(self.out_queue.popleft())
            # perform queued joins
            if not self.dead and (self.private_name is not None and len(self.queue_joins) > 0):
                self.logger.debug('Joining >pending< groups: %s' % self.queue_joins)
                while len(self.queue_joins) > 0:
                    self.join(self.queue_joins.pop())
        print 'IO Thread exiting'
        self.io_active = False
    
    def loop(self, count=None, timeout=0.1, timer_interval=10):
        '''factor out expire_every into a generalized timer that calls up into listener'''
        if self.io_active:
            print 'ERROR: using loop() at same time as background IO thread is not valid/smart.'
            raise IOError('Cannot do asyncore IO in two different threads')
        main_loop = 0
        #self.listener._process_timer(self) #hmm, to do or not to do...
        while not self.dead and (count is None or main_loop < count):
            main_loop += 1
            asyncore.loop(timeout=timeout/5, count=5, use_poll=True)
            if self.private_name is not None and len(self.queue_joins) > 0:
                self.logger.debug('Joining >pending< groups: %s' % self.queue_joins)
                q_groups = self.queue_joins
                self.queue_joins = []
                self.join(q_groups)
            # every N iterations, check for timed out pings
            if timer_interval and main_loop % timer_interval == 1:
                self.listener._process_timer(self)

    def poll(self, timeout=0.001):
        if self.dead:
            return False
        asyncore.loop(timeout=timeout, count=1)
        return True

    def wait_for_connection(self, timeout=10, sleep_delay=0.1):
        '''Spend time in self.poll() until the timeout expires, or we are connected, whichever first.
        Return boolean indicating if we are connected yet.  Or not.'''
        time_end = time.time() + timeout
        while self.private_name is None and time.time() < time_end:
            if self.dead:
                return False
            self.poll(timeout/100)
            time.sleep(sleep_delay)
        return self.private_name is not None

    def _drop(self):
        self.dead = True
        self.io_ready.clear()
        self.connected = False
        self.close()
        self.discard_buffers()
        self.ibuffer = ''
        self.ibuffer_start = 0
        self.private_name = None

    def _dispatch(self, message):
        listener = self.listener
        if listener is not None:
            if isinstance(message, MembershipMessage):
                listener._process_membership(self, message)
            else:
                listener._process_data(self, message)

    def collect_incoming_data(self, data):
        '''Buffer the data'''
        self.ibuffer += data

    def found_terminator(self):
        data = self.ibuffer[self.ibuffer_start:(self.ibuffer_start+self.need_bytes)]
        self.ibuffer_start += self.need_bytes
        if len(self.ibuffer) > 500:
            self.ibuffer = self.ibuffer[self.ibuffer_start:]
            self.ibuffer_start = 0
        next_cb = self.next_state
        next_cb(data)

    def wait_bytes(self, need_bytes, next_state):
        need_bytes = int(need_bytes) # py 2.4 fixup for struct.unpack()'s longs not satisfying isinstance(int)
        self.need_bytes = need_bytes
        self.next_state = next_state
        self.set_terminator(need_bytes)

    def st_auth_read(self, data):
        self.logger.debug('STATE: st_auth_read')
        (authlen,) = struct.unpack('b', data)
        if authlen < 0:
            self.logger.debug('Failed authentication to server: client name collision?')
            self._drop()
            self.listener._process_error(self, SpreadException(authlen))
            return
        self.wait_bytes(authlen, self.st_auth_process)

    def st_auth_process(self, data):
        self.logger.debug('STATE: st_auth_process')
        methods = data.rstrip().split(' ') # space delimited?
        if 'NULL' not in methods: # TODO: add 'IP' support at some point
            self.logger.critical('Spread server does not accept our NULL authentication. Server permited methods are: "%s"' % (data))
            self._drop()
            self.listener._process_error(self, SpreadException(-9))
            return
        msg_auth = SpreadProto.AUTH_PKT
        self.wait_bytes(1, self.st_read_session)
        self.push(msg_auth)
        return

    def st_read_session(self, data):
        self.logger.debug('STATE: st_read_session')
        (accept,) = struct.unpack('b', data)
        if accept != 1:
            self.logger.critical('Failed authentication / connection: %s' % (accept))
            self._drop()
            self.listener._process_error(self, SpreadException(accept))
            return
        self.wait_bytes(3, self.st_read_version)

    def st_read_version(self, data):
        self.logger.debug('STATE: st_read_version')
        (majorVersion, minorVersion, patchVersion) = struct.unpack('bbb', data)
        self.logger.info('Server reports it is Spread version: %d.%d.%d' % (majorVersion, minorVersion, patchVersion))
        version = (majorVersion | minorVersion | patchVersion)
        if version == -1: # when does this happen?
            self._drop()
            self.listener._process_error(self, SpreadException(version))
            return
        self.server_version = (majorVersion, minorVersion, patchVersion)
        self.wait_bytes(1, self.st_read_private_name)

    def st_read_private_name(self, data):
        self.logger.debug('STATE: st_read_private_name')
        (group_len,) = struct.unpack('b', data)
        if group_len == -1:
            self._drop()
            self.listener._process_error(self, SpreadException(group_len))
            return
        self.wait_bytes(group_len, self.st_set_private)

    def st_set_private(self, data):
        self.logger.debug('STATE: st_set_private')
        self.private_name = data
        self.logger.info('Spread session established to server: %s:%d, my private name is: "%s"' % (self.host, self.port, self.private_name))
        self.listener._process_authenticated(self)
        self.wait_bytes(48, self.st_read_header)
        self.io_ready.set()

    def st_read_header(self, data):
        self.logger.debug('STATE: st_read_header')
        (svc_type, sender, num_groups, mesg_type, mesg_len) = self.struct_hdr(data)
        # TODO: add code to flip endianness of svc_type and mesg_type if necessary (independently?)
        ENDIAN_TEST = 0x80000080
        endian_wrong = (svc_type & ENDIAN_TEST) == 0
        svc_type &= ~ENDIAN_TEST
        mesg_type &= ~ENDIAN_TEST
        mesg_type = mesg_type >> 8
        # trim trailing nulls on sender
        tail_null = sender.find('\x00')
        if tail_null >= 0:
            sender = sender[0:tail_null]
        self.logger.debug('Svc type: 0x%04x  sender="%s"  mesg_type: 0x%08x   num_groups: %d   mesg_len: %d' % (svc_type, sender, mesg_type, num_groups, mesg_len))
        # pass header to message factory to build up the SpreadMessage
        factory_mesg = self.mfactory.process_header(svc_type, mesg_type, sender, num_groups, mesg_len)
        self.logger.debug('- mesg_type = %d and hex 0x%04x' % (mesg_type, mesg_type))
        self.logger.debug('- sender="%s"  num_groups: %d   mesg_len:%d' % (sender, num_groups, mesg_len))
        if num_groups > 0:
            self.wait_bytes(num_groups * SpreadProto.MAX_GROUP_LEN, self.st_read_groups)
            return
        if mesg_len > 0:
            self.wait_bytes(mesg_len, self.st_read_message)
            return
        # At this point, we have a full message in factory_mesg, even though it has no groups or body
        self._dispatch(factory_mesg)
        self.wait_bytes(48, self.st_read_header)
        return

    def st_read_groups(self, data):
        self.logger.debug('STATE: st_read_groups')
        group_packer = SpreadProto.GROUP_FMTS[self.mfactory.num_groups] # '32s' * len(gname)
        groups_padded = struct.unpack(group_packer, data)
        groups = [ g[0:g.find('\x00')] for g in groups_padded ] # _grouplist_trim(groups_padded)
        factory_mesg = self.mfactory.process_groups(groups)
        mesg_len = self.mfactory.mesg_len
        if mesg_len > 0:
            self.wait_bytes(mesg_len, self.st_read_message)
            return
        print 'about to _dispatch'
        # handle case of no message body, on self-leave
        self._dispatch(factory_mesg)
        print 'about to wait_bytes'
        self.wait_bytes(48, self.st_read_header)
        return

    def st_read_message(self, data):
        self.logger.debug('STATE: st_read_message')
        self.msg_count += 1
        self.wait_bytes(48, self.st_read_header) # always going to a new message next
        factory_mesg = self.mfactory.process_data(data)
        self._dispatch(factory_mesg)

    def _send(self, data):
        if self.io_active:
            self.out_queue.append(data)
        else:
            self.push(data)

    # only works after getting connected
    def join(self, group):
        if self.private_name is None:
            self.logger.warn('No private channel name known yet from server... queueing up group join for: %s' % (group))
            self.queue_joins.append(group)
            return False
        send_head = SpreadProto.protocol_create(SpreadProto.JOIN_PKT, 0, self.private_name, [group], 0)
        self._send(send_head)
        return True

    def leave(self, group):
        if self.private_name is None:
            self.logger.critical('No private channel name known yet from server... Failed leave() message')
            return False
        send_head = SpreadProto.protocol_create(SpreadProto.LEAVE_PKT, 0, self.private_name, [group], 0)
        self._send(send_head)
        return True

    def disconnect(self):
        if self.private_name is None:
            self.logger.critical('No private channel name known yet from server... Failed disconnect() message')
            return False
        who = self.private_name
        send_head = SpreadProto.protocol_create(SpreadProto.KILL_PKT, 0, who, [who], 0)
        self._send(send_head)
        self._drop()
        return True

    def multicast(self, groups, message, mesg_type, self_discard=True, service_type=ServiceTypes.SAFE_MESS):
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
            self.logger.critical('No private channel name known yet from server... Failed multicast message')
            return False
        #print 'multicast(groups=%s, message=%s, mesg_type=%d)' % (groups, message, mesg_type)
        data_len = len(message)
        if self_discard:
            svc_type_pkt = self.proto.send_pkt_selfdisc # was: SpreadProto.SEND_SELFDISCARD_PKT
        else:
            svc_type_pkt = self.proto.send_pkt # was: SpreadProto.SEND_PKT
        header = SpreadProto.protocol_create(svc_type_pkt, mesg_type, self.private_name, groups, data_len)
        pkt = header + message
        self._send(pkt)
        return True

    def unicast(self, group, message, mesg_type):
        '''alias for sending to a single destination, and disables SELF_DISCARD (in case it is a self ping)'''
        return self.multicast([group], message, mesg_type, self_discard=False)


class SpreadException(Exception):
    '''SpreadException class from pyspread code by Quinfeng.
    Note: This should be a smaller set of exception classes that map to
    categories of problems, instead of this enumerated list of errno strings.'''
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
        self.errno = errno
        self.msg = SpreadException.errors.get(errno, 'unrecognized error')

    def __str__(self):
        return ('SpreadException(%d) # %s' % (self.errno, self.msg))

    def __repr__(self):
        return (self.__str__())

if __name__ == '__main__':
    # do some unit testing here... not easy to imagine without a server to talk to
    pass
