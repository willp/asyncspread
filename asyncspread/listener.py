#!/usr/bin/env python
from message import *
from services import *
import time

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
            message.sender == conn.session_name and
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
        conn.unicast(conn.session_name, payload, mesg_type)

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
