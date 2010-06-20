#!/usr/bin/env python
import socket, struct, copy, asyncore, asynchat, time, logging, sys, threading, traceback, itertools
from collections import deque

'''This code is released for use under the Gnu Public License V3 (GPLv3).

Thanks to Qingfeng for the initial version of code that inspired this rewrite.

Thanks to Spread Concepts, LLC., especially Amir Yair and Jonathan Stanton for
the Spread toolkit.

Please accept my humble apologies for this code being somewhat disorganized.
It is a work in progress!

Author:  "J. Will Pierce" <willp@nuclei.com>
'''

class NullLogHandler(logging.Handler):
    '''Log null handler for polite logging'''
    def emit(self, record): pass

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

    (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH) = (4, 1, 0)

    # Pre-create some format strings
    # Don't send to more than MAX_GROUPS groups at once, increase if necessary
    MAX_GROUPS = 1000
    # This list will consume 1000*3 = 3 KB, plus overhead.  Worth it to spend the RAM.
    GROUP_FMTS = [ GROUP_FMT * i for i in xrange(MAX_GROUPS) ]

    # Encoded message headers
    JOIN_PKT = struct.pack('!I', ServiceTypes.JOIN)
    LEAVE_PKT = struct.pack('!I', ServiceTypes.LEAVE)
    KILL_PKT = struct.pack('!I', ServiceTypes.KILL)

    # Handshake message parts
    AUTH_PKT = struct.pack('90s', 'NULL')

    def __init__(self):
        self.set_level()

    def set_level(self, default_type=ServiceTypes.SAFE_MESS):
        self.default_type = default_type
        self.send_pkt = struct.pack('!I', default_type)
        self.send_pkt_selfdisc = struct.pack('!I', default_type | ServiceTypes.SELF_DISCARD)

    @staticmethod
    def protocol_create(svcType, mesgtype, private_name, group_names, data_len=0):
        #print 'protocol_create(len(svctype)=%d, mesgtype=%s, private_name=%s, group_names=%s, data_len=%d)' % (len(svcType), mesgtype, private_name, group_names, data_len)
        mesgtype_str = struct.pack('<I', (mesgtype & 0xffff) << 8)
        msg_hdr = struct.pack('>32sI4sI', private_name, len(group_names), mesgtype_str, data_len)
        grp_tag  = SpreadProto.GROUP_FMTS[len(group_names)] # '32s' * len(gname)
        grp_hdr = struct.pack(grp_tag, *group_names)
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
        return struct.pack(connect_fmt, SpreadProto.VERSION_MAJOR, SpreadProto.VERSION_MINOR, SpreadProto.VERSION_PATCH, mem_opts, name_len, my_name)

    def get_send_pkt(self, self_discard):
        if self_discard:
            return self.send_pkt_selfdisc
        return self.send_pkt

class SpreadMessage(object):
    def _set_data(self, data):
        self.data = data

    def _set_grps(self, groups):
        self.groups = groups

class DataMessage(SpreadMessage):
    def __init__(self, sender, mesg_type, self_discarded):
        SpreadMessage.__init__(self)
        self.sender = sender
        self.mesg_type = mesg_type
        self.self_discarded = self_discarded
        self.groups = []
        self.data = ''

    def __repr__(self):
        return '%s:  sender:%s,  mesg_type:%d,  groups:%s,  self-disc:%s,  data:"%s"' % (self.__class__,
                            self.sender, self.mesg_type, self.groups, self.self_discarded, self.data)

class OpaqueMessage(SpreadMessage):
    def __init__(self, sender, svc_type, mesg_type, is_membership):
        SpreadMessage.__init__(self)
        self.sender = sender
        self.svc_type = svc_type
        self.mesg_type = mesg_type
        self.is_membership = is_membership
        self.groups = []
        self.data = ''

    def __repr__(self):
        return '%s:  svc_type: 0x%04x  mesg_type:%d  sender:%s  groups:%s  data(%d bytes):"%s"' % (self.svc_type,
                    self.mesg_type, self.__class__, self.sender, self.groups, len(self.data), self.data)

class MembershipMessage(SpreadMessage):
    def __init__(self, group):
        SpreadMessage.__init__(self)
        self.group = group
        self.members = []

    def _set_grps(self, groups):
        self.members = groups

    def __repr__(self):
        return '%s:  group:%s,  members:%s' % (self.__class__, self.group, self.members)

class TransitionalMessage(MembershipMessage):
    pass

class JoinMessage(MembershipMessage):
    pass

class DisconnectMessage(MembershipMessage):
    pass

class NetworkMessage(MembershipMessage):
    pass

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
            # fall-thru error here, unknown change-cause!
            print 'ERROR: unknown membership change CAUSE.  svc_type=0x%04x' % (svc_type) # TODO: raise exception?
            self.this_mesg = OpaqueMessage(sender, svc_type, mesg_type, is_membership=True)
            return self.this_mesg
        elif svc_type & ServiceTypes.CAUSED_BY_LEAVE:
            # self-LEAVE message!
            self.this_mesg = LeaveMessage(sender, True)
            return self.this_mesg
        # strange, sometimes this is received NOT as a regular membership message?
        if svc_type & ServiceTypes.TRANSITION_MESS:
            # TRANSITIONAL message, a type of membership message
            self.this_mesg = TransitionalMessage(sender)
            return self.this_mesg
        # fall-thru error here, unknown type
        #print 'ERROR: unknown message type, neither DataMessage nor MembershipMessage marked.  svc_type=0x%04x' % (svc_type) # TODO: raise exception?
        self.this_mesg = OpaqueMessage(sender, svc_type, mesg_type, is_membership=False)
        return self.this_mesg
        #return None


class SpreadListener(object):
    def __init__(self):
        self._clear_groups()

    def _clear_groups(self):
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
    # TODO: wrap the handle_() methods with try/except?

    def _process_data(self, conn, message):
        self.handle_data(conn, message)

    def _process_connected(self, conn):
        self.handle_connected(conn)

    def _process_error(self, conn, exc):
        self.handle_error(conn, exc)

    def _process_dropped(self, conn):
        self.handle_dropped(conn)
        # AFTER doing handle_dropped(), clear out the group membership
        self._clear_groups()

    def handle_connected(self, conn):
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
        self.clear_stats()

    def clear_stats(self):
        # counters
        self.ping_sent = 0
        self.ping_recv = 0
        self.ping_late = 0

    def pktloss(self):
        if self.ping_sent == 0:
            return 0
        pktloss = self.ping_recv / self.ping_sent * 100.0
        return pktloss


    def _process_data(self, conn, message):
        data = message.data
        if (message.mesg_type == self.ping_mtype and
            len(message.groups) == 1 and
            message.sender == conn.private_name and
            len(data) > 0):
            (head, ping_id, timestamp) = data.split(':')
            ping_id = int(ping_id)
            elapsed = time.time() - float(timestamp)
            # pings expire, handle late arrivals here, devour silently
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
        self.ping_id += 1 # not thread-safe here, also may wrap, oh well
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
    def __init__(self, cb_conn=None, cb_data=None, cb_dropped=None, cb_error=None):
        '''Creates a new callback listener.

        @param cb_conn: callback to be invoked as cb_conn(listener, conn) when the session is authenticated and so is officially connected
        @param cb_data: callback to be invoked as cb_data(listener, conn, message) when any data message arrives on any group
        @param cb_dropped: callback to be invoked as cb_dropped(listener, conn) when the connection is dropped
        @param cb_error: callback to be invoked as cb_error(listener, conn, exception) when an error happens
        '''
        SpreadListener.__init__(self)
        self.cb_conn = cb_conn
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

    def handle_connected(self, conn):
        if self.cb_conn:
            self.cb_conn(self, conn)

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
                    print 'Exception in client callback' # TODO: add traceback output here
                    # also TODO: perhaps invoke an error handler callback? or use logging?

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

    def join_with_wait(self, conn, group, timeout=10):
        '''Join group, and return when the join was successfully joined, or if the timeout expired'''
        expire_time = time.time() + timeout
        joined = False
        members = []
        def done(conn, group, membership):
            joined = True
            members = membership
            print 'GCB invoked! Group "%s" joined! Members: %s' % (group, members)
        self.set_group_cb(group, GroupCallback(cb_start=done))
        conn.join(group)
        while time.time() < expire_time and not joined:
            conn.loop(1)
            print 'waiting for join to group "%s"' % (group)
            time.sleep(0.1)
        return joined

class DebugListener(SpreadListener):
    '''super verbose'''

    def handle_connected(self, conn):
        print 'DEBUG: Got connected, new session is ready!'

    def handle_dropped(self, conn):
        print 'DEBUG: Lost connection!'

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
            print 'DEBUG: Parent class threw an exception in handle_timer()' # TODO: print traceback here

class async_chat26(asynchat.async_chat):
    '''helper to fix for python2.4 asynchat missing a 'map' parameter'''
    def __init__ (self, conn=None, map=None):
        # if python version < 2.6:
        if sys.version_info[0:2] < (2,6):
            # python 2.4 and 2.5 need to do this:
            self.ac_in_buffer = ''
            self.ac_out_buffer = ''
            self.producer_fifo = asynchat.fifo()
            # and here is the fix, I'm including 'map' to the superclass constructor here:
            asyncore.dispatcher.__init__ (self, conn, map)
        else:
            # otherwise, we defer 100% to the parent class, since it works fine
            asynchat.async_chat.__init__(self, conn, map)

class AsyncSpread(async_chat26): # was asynchat.async_chat
    '''Asynchronous client API for Spread 4.x group messaging.'''
    def __init__(self, name, host, port,
                 listener=None,
                 membership_notifications=True,
                 priority_high=False,
                 timer_interval=1.0,
                 keepalive=True,
                 map=None):
        '''Create object representing asynchronous connection to a spread daemon.

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
        @param timer_interval: number of seconds between invocations to handle_timer() on listener
        @type timer_interval: float
        @param keepalive: enable or disable TCP_KEEPALIVE on the socket, strongly recommended you leave this ENABLED
        @type keepalive: bool
        '''
        if map is not None:
            self.my_map = map
        else:
            self.my_map = dict()
        async_chat26.__init__(self, map=self.my_map)
        self.name, self.host, self.port = (name, host, port)
        self.membership_notifications = membership_notifications
        self.priority_high = priority_high
        # the SpreadListener object to invoke for message and connection events
        self.listener = listener
        # TCP keepalive settings
        self.keepalive = keepalive
        self.keepalive_idle = 10 # every 10 seconds of idleness, send a keepalive (empty PSH/ACK)
        self.keepalive_maxdrop = 6 # one minute
        # initialize some basics
        self.unpack_header = self.make_unpack_header()
        self.logger = logging.getLogger()
        self.proto = SpreadProto()
        self.mfactory = None
        self._clear_ibuffer()
        #
        self.private_name = None
        self.session_up = False
        self.msg_count = 0
        # deal with timer:
        self.timer_interval = timer_interval
        self._reset_timer()
        # more settings
        self.queue_joins = []
        self.dead = False
        # state machine for protocol processing uses these
        self.need_bytes = 0
        self.next_state = None
        # thread/io data
        self.io_active = False # TODO: thread only
        self.io_ready = threading.Event() # TODO: thread only
        self.do_reconnect = False
        self.shutdown = False

    def __str__(self):
        return '<%s>: name="%s", connected=%s, server="%s:%d", private_name="%s"' % (self.__class__, self.name, self.connected, self.host, self.port, self.private_name)

    def _do_connect(self):
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.keepalive:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) # enable
                self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, self.keepalive_idle)
                self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, self.keepalive_idle)
                self.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, self.keepalive_maxdrop)
            except:
                self.logger.warning('Failed setting TCP KEEPALVIE on socket. Firewall issues may cause connection to silently become a black hole.')
                self.keepalive = False
        self.dead = False
        print 'attempting self.connect() to:',self.host, self.port
        ret = self.connect((self.host, self.port))
        print 'CONNECT:', ret

    def start_connect(self, timeout=10):
        print 'start_connect() timeout:', timeout
        self._do_connect()
        return self.wait_for_connection(timeout)

    def wait_for_connection(self, timeout=10, sleep_delay=0.1):
        '''Spend time in self.poll() until the timeout expires, or we are connected, whichever first.
        Return boolean indicating if we are connected yet.  Or not.'''
        time_end = time.time() + timeout
        while self.private_name is None and time.time() < time_end:
            print 'Waiting for connection...'
            if self.dead:
                return False
            self.poll(timeout/100)
            time.sleep(sleep_delay)
        print 'wait_for_connection() returning. private_name:', self.private_name
        return self.private_name is not None

    def poll(self, timeout=0.001):
        if self.dead:
            return False
        asyncore.loop(timeout=timeout, count=1, map=self.my_map)
        return True

    def loop(self, timeout=None, slice=0.1):
        '''factor out expire_every into a generalized timer that calls up into listener'''
        if self.io_active:
            print 'ERROR: using loop() at same time as background IO thread is not valid/smart.'
            raise IOError('Cannot do asyncore IO in two different threads')
        main_loop = 0
        timeout = timeout / slice
        print 'TIMEOUT is now:', timeout
        while not self.dead and (timeout is None or main_loop <= timeout):
            main_loop += 1
            asyncore.loop(timeout=slice, count=1, use_poll=True, map=self.my_map)
            # every N iterations, check for timed out pings
            if self._is_timer():
                self.listener._process_timer(self)

    def set_level(self, level):
        '''totally delegated to internal SpreadProto object'''
        self.proto.set_level(level)

    def _unpack_header(self, payload):
        '''used for python < 2.5 where the struct module doesn't offer the
        more optimized struct.Struct class for holding pre-compiled struct formats.'''
        return struct.unpack(SpreadProto.HEADER_FMT, payload)

    def make_unpack_header(self):
        try:
            precompiled = struct.Struct(SpreadProto.HEADER_FMT)
            return precompiled.unpack # bound method
        except: # python <= 2.4 support
            return self._unpack_header

    def _clear_ibuffer(self):
        self.ibuffer = ''
        self.ibuffer_start = 0

    def _reset_timer(self, delay=None):
        if delay is None:
            delay = self.timer_interval
        self.timer_next = time.time() + delay

    def _is_timer(self):
        now = time.time()
        if now >= self.timer_next:
            self._reset_timer()
            return True
        return False

    def handle_connect(self):
        self.mfactory = SpreadMessageFactory()
        self.logger.debug('handle_connect(): got TCP connection to server, sending credentials')
        msg_connect = SpreadProto.protocol_connect(self.name, self.membership_notifications, self.priority_high)
        self.wait_bytes(1, self.st_auth_read)
        self.push(msg_connect)

    def handle_close(self):
        self.logger.warning('Connection lost to server: %s:%d' % (self.host, self.port))
        self.dead = True
        self.private_name = None
        self.mfactory = None
        self.close()
        self.listener._process_dropped(self)

    def handle_error(self):
        (exc_type, exc_val, tb) = sys.exc_info()
        self.logger.warning('handle_error(): Got exception: %s' % exc_val)
        self.logger.info('Traceback: ' + traceback.format_exc())
        self._drop()
        sys.exc_clear()
        self.listener._process_error(self, exc_val)
        self.listener._process_dropped(self)

    def _drop(self):
        self.io_ready.clear()
        self.dead = True
        self.session_up = False
        self.close() # changes self.connected to False, usually
        self.discard_buffers()
        self._clear_ibuffer()
        self.private_name = None
        if self.connected:
            self.connected = False

    def _send(self, data):
        self.push(data)

    def _dispatch(self, message):
        listener = self.listener
        if listener is not None:
            # Listeners should not throw exceptions here
            if isinstance(message, MembershipMessage):
                listener._process_membership(self, message)
            elif isinstance(message, DataMessage):
                listener._process_data(self, message)
            elif isinstance(message, OpaqueMessage):
                # opaque messages go here. TODO: convert to logging
                print 'Unknown message received as OpaqueMessage:', message
                print 'NO handling known/possible...'
                print 'Ignoring unparsed opaque message'
                # let's hope this never happens
            else:
                # this never happens. assert() here
                assert message, 'Unexpected type of message: %s' % (type(message))

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
            exc = SpreadAuthException(authlen)
            self.logger.critical('Failed authentication to server: Exception: %s' % (exc))
            self._drop()
            self.listener._process_error(self, exc)
            return
        self.wait_bytes(authlen, self.st_auth_process)

    def st_auth_process(self, data):
        self.logger.debug('STATE: st_auth_process')
        methods = data.rstrip().split(' ') # space delimited?
        if 'NULL' not in methods: # TODO: add 'IP' support at some point
            self.logger.critical('Spread server does not accept our NULL authentication. Server permited methods are: "%s"' % (data))
            self._drop()
            self.listener._process_error(self, SpreadAuthException(-9))
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
        self.session_up = True
        self.logger.info('Spread session established to server:  %s:%d' % (self.host, self.port))
        self.logger.info('My private name for this connection is: "%s"' % (self.private_name))
        self.io_ready.set()
        self.listener._process_connected(self)
        self.wait_bytes(48, self.st_read_header)

    def st_read_header(self, data):
        self.logger.debug('STATE: st_read_header')
        (svc_type, sender, num_groups, mesg_type, mesg_len) = self.unpack_header(data)
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
        # AFAICT empty messages with no groups are self-leave messages, useful!
        self.wait_bytes(48, self.st_read_header)
        self._dispatch(factory_mesg)

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
        # handle case of no message body, on self-leave
        self.wait_bytes(48, self.st_read_header)
        self._dispatch(factory_mesg)

    def st_read_message(self, data):
        self.logger.debug('STATE: st_read_message')
        self.msg_count += 1
        factory_mesg = self.mfactory.process_data(data)
        self.wait_bytes(48, self.st_read_header) # always going to a new message next
        self._dispatch(factory_mesg)

    def join(self, group):
        if self.private_name is None:
            self.logger.critical('Not connected to spread. Cannot join group "%s"' % (group))
            raise SpreadException(100) # not connected
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
            return False # is we're not connected, just return False instead of raising an exception
        who = self.private_name
        send_head = SpreadProto.protocol_create(SpreadProto.KILL_PKT, 0, who, [who], 0)
        self._send(send_head)
        self._drop()
        self.shutdown = True
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
            self.logger.critical('Not connected to spread. Cannot send multicast message to group(s) "%s"' % (groups))
            raise SpreadException(100)
        #print 'multicast(groups=%s, message=%s, mesg_type=%d)' % (groups, message, mesg_type)
        data_len = len(message)
        svc_type_pkt = self.proto.get_send_pkt(self_discard)
        header = SpreadProto.protocol_create(svc_type_pkt, mesg_type, self.private_name, groups, data_len)
        pkt = header + message
        self._send(pkt)
        return True

    def unicast(self, group, message, mesg_type):
        '''alias for sending to a single destination, and disables SELF_DISCARD (in case it is a self ping)'''
        return self.multicast([group], message, mesg_type, self_discard=False)

class AsyncSpreadThreaded(AsyncSpread):
    '''Thread-safe subclass of AsyncSpread which will implement a background IO thread, or allow
    you to implement your own IO thread (since asyncore/asynchat is not thread-safe itself.
    
    Typical implementation will be:
    - user threads invoke various methods to initiate a connect, join, leave, multicast, unicast, disconnect, etc
    - blocking methods (like connect) will let user specify a timeout
    - all other methods operate only on a queue that the IO thread will process
    - ONLY the IO thread runs asyncore.loop()
    -- therefore, ONLY the IO thread runs in the st_* methods for processing the protocol
    - ALL user callbacks will be invoked by a separate thread (perhaps this happens in a run() method? so the
    user's invoking thread is used as the response thread.  could keep things pretty stable.)
    - IO thread is daemonic
    - exceptions are only raised to the user thread
    - IO thread runs all the time? or only when the connection is up?
    
    The main AsyncSpread class will turn into a class that you have to invoke .loop() against, to ask it to do asyncore.loop()
    ... OR... do I want to be more complicated....
    
    Think about simple client case: I want to connect up to the mesg bus, and send one request to a channel and
    gather up responses and then disconnect or exit.  The threaded method would be a bit overkill, so the nonthreaded
    version would work nicely, as long as I have a way to wait for responses.  Maybe I have a wait() method that takes
    as arguments the # of DataMessages to wait for, or a maximum timeout.  But.. since the handler_*() methods would
    be invoked for the responses (or callbacklistener does stuff), then maybe I should just use a loop() method that
    checks a flag and does a graceful disconnect and close() when the flag is set.  There could be a simple method
    that would set this flag.  Hmm.  That seems most convenient to the user.  Each handle_data() call would decide whether
    to throw the flag or not.
    '''
    def __init__(self, *args, **kwargs):
        kwargs['map'] = dict() # ensure all instances get their own distinct map object
        self.my_map = kwargs['map']
        AsyncSpread.__init__(self, *args, **kwargs)
        print 'NonThreaded constructor done, Threaded stuff happening now'
        self.io_thread = threading.Event() # TODO: thread only
        self.io_thread_lock = threading.Lock()
        self.io_thread_active = False
        self.do_reconnect = True
        # outbound messages for threaded uses
        self.out_queue = deque()

    def _send(self, pkt):
        self.out_queue.append(pkt)

    def start_io_thread(self):
        '''This is not truly thread safe, not really. There is a big race condition here.
        1. obtain lock on io_thread_lock (BLOCKING)
        2. check self.io_thread_active
        3. if False, start thread and set True
        4. else release lock and return
        '''
        self.io_thread_lock.acquire() #blocks
        if not self.io_thread_active:
            name_str = 'AsyncSpreadThreaded I/O Thread: %s' % (self.name)
            thr = threading.Thread(target=self.do_io, args=[name_str], name=name_str)
            thr.daemon=True
            thr.start()
            self.io_thread_active = True
        self.io_thread_lock.release()
        return

    def start_connect(self, timeout=10):
        self.do_reconnect = True
        print 'start_connect() timeout:', timeout
        return self.wait_for_connection(timeout)

    def wait_for_connection(self, timeout=10):
        '''If io thread is not started, start it.
        Then wait up to timeout seconds for connection to be completed.'''
        if not self.io_thread_active:
            print 'wait_for_connection(): really firing up IO thread'
            self.start_io_thread()
        print 'wait_for_connection(): Waiting up to %0.3f seconds for io_ready to be set()' % (timeout)
        self.io_ready.wait(timeout)
        return self.private_name is not None

    def do_io(self, thr_name):
        '''This is the main IO thread's main loop for threaded asyncspread usage...  It
        looks for new data to send from the output queues and checks the socket for
        new messages, and invokes response callbacks through the listener object.

        If the connection is shut down, this thread will wait until reconnect is set to
        True, and initiate a new connection.  I think.
        
        This logic is insane.  Needs MAJOR help / refactoring.
        '''
        me = threading.local()
        me.thr_name = thr_name
        print 'Doing io in do_io()'
        main_loop = 0
        while not self.shutdown:
            main_loop += 1
            # handle timer
            if self._is_timer():
                self.listener._process_timer(self)
            # handle reconnect
            if self.do_reconnect and not self.private_name:
                self.do_reconnect = False # reset flag
                print 'IO thread trying to self._do_connect()...  reset do_reconnect to False'
                self._do_connect()
                continue
            if not self.dead:
                asyncore.loop(timeout=0.01, count=2, use_poll=True, map=self.my_map)
                # make sure not to deliver any messages if the session isn't ready
                if self.private_name:
                    # deliver queued up outbound data
                    while len(self.out_queue) > 0 and not self.shutdown:
                        self.push(self.out_queue.popleft())
                    # perform queued joins
                    if len(self.queue_joins) > 0 and not self.shutdown:
                        self.logger.debug('Joining >pending< groups: %s' % self.queue_joins)
                        while len(self.queue_joins) > 0:
                            self.join(self.queue_joins.pop())
        print 'IO Thread exiting'
        self._drop()

    def loop(self, timeout=None, slice=0.001):
        print 'THREADED loop() called!'
        time.sleep(timeout)  # just sleep in this case? or raise exception?

    def poll(self, timeout=0.001):
        pass#time.sleep(timeout)

class SpreadException(Exception):
    '''SpreadException class from pyspread code by Quinfeng.
    Note: This should be a smaller set of exception classes that map to
    categories of problems, instead of this enumerated list of errno strings.'''
    errors = {-1: 'ILLEGAL_SPREAD', # TODO: eliminate unnecessary errno values
        -2: 'COULD_NOT_CONNECT',
        -3: 'REJECT_QUOTA',
        -4: 'REJECT_NO_NAME', # doesn't happen: if you send empty string, server assigns your name
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
        -18: 'NET_ERROR_ON_SESSION',
       100: 'Not connected to spread server.' }

    def __init__(self, errno):
        Exception.__init__(self)
        self.errno = errno
        self.type = 'SpreadException' # TODO: should be cleaner
        self.msg = SpreadException.errors.get(errno, 'unrecognized error')

    def __str__(self):
        return ('%s(%d) # %s' % (self.type, self.errno, self.msg))

    def __repr__(self):
        return (self.__str__())

class SpreadAuthException(SpreadException):
    def __init__(self, errno):
        SpreadException.__init__(self, errno)
        self.type = 'SpreadAuthException' # TODO: clean up





logging.getLogger().addHandler(NullLogHandler())

if __name__ == '__main__':
    # do some unit testing here... not easy to imagine without a server to talk to
    pass
