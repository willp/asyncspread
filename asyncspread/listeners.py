'''Spread Listeners are implemented here'''
import time, logging, threading, traceback, sys
from asyncspread.message import *

def print_tb(logger, who):
        (exc_type, exc_val, tback) = sys.exc_info()
        logger.warning('%s: Got exception: %s: %s' % (who, type(exc_val), exc_val))
        logger.info('Traceback: ' + traceback.format_exc())
        sys.exc_clear()

class SpreadListener(object):
    '''Base generic SpreadListener class which implements the core functionality of
    processing membership notifications, providing an interface to query them, and
    stub methods for the AsyncSpread classes to invoke on certain events, like receiving
    messages, membership notifications, connection failures, and connection success.'''
    def __init__(self):
        self._clear_groups()
        self.logger = logging.getLogger()

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
            try:
                self.handle_group_trans(conn, group)
            except:
                print_tb(self.logger, 'SpreadListener.handle_group_trans(group=%s)' % (group))
            return
        new_membership = set(message.members)
        # new group!
        #if not self.groups.has_key(group):
        if not group in self.groups:
            self.groups[group] = new_membership
            try:
                self.handle_group_start(conn, group, new_membership)
            except:
                print_tb(self.logger, 'SpreadListener.handle_group_start(group=%s)' % (group))
            return
        old_membership = self.groups[group]
        if (isinstance(message, LeaveMessage) and message.self_leave) or len(new_membership) == 0:
            del self.groups[group]
            try:
                self.handle_group_end(conn, group, old_membership)
            except:
                print_tb(self.logger, 'SpreadListener.handle_group_end(group=%s)' % (group))
            return
        # now compute differences
        differences = old_membership ^ new_membership # symmetric difference
        self.groups[group] = new_membership
        cause = type(message)
        # notify if we have a network split event
        if isinstance(message, NetworkMessage):
            changes = len(new_membership) - len(old_membership)
            try:
                self.handle_network_split(conn, group, changes, old_membership, new_membership)
            except:
                print_tb(self.logger, 'SpreadListener.handle_network_split')
        for member in differences:
            if member not in old_membership:
                # this is an add
                try:
                    self.handle_group_join(conn, group, member, cause)
                except:
                    print_tb(self.logger, 'SpreadListener.handle_group_join(group=%s)' % (group))
            else:
                # this is a leave/departure
                try:
                    self.handle_group_leave(conn, group, member, cause)
                except:
                    print_tb(self.logger, 'SpreadListener.handle_group_leave(group=%s)' % (group))

    def get_group_members(self, group):
        return self.groups[group]

    # this method is called once every so often by the "main loop" of AsyncSpread
    def _process_timer(self, conn):
        try:
            self.handle_timer(conn)
        except:
            print_tb(self.logger, 'SpreadListener.handle_timer')

    def handle_timer(self, conn):
        '''override this to have your listener invoked once in a while (configurable?) to do maintenance'''
        pass

    # a series of _process* methods that in just call their respective (overriden?) handle_* versions
    # these are here to make it easier for subclasses to override handle_* and permit
    # future enhancements to the base class, similar to how _process_membership() does
    # bookkeeping, before calling handle_*() methods
    # TODO: wrap the handle_() methods with try/except?

    def _process_data(self, conn, message):
        try:
            self.handle_data(conn, message)
        except:
            print_tb(self.logger, 'SpreadListener.handle_data')

    def _process_connected(self, conn):
        try:
            self.handle_connected(conn)
        except:
            print_tb(self.logger, 'SpreadListener.handle_connected')

    def _process_error(self, conn, exc):
        try:
            self.handle_error(conn, exc)
        except:
            print_tb(self.logger, 'SpreadListener.handle_error')

    def _process_dropped(self, conn):
        try:
            self.handle_dropped(conn)
        except:
            print_tb(self.logger, 'SpreadListener.handle_dropped')
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
        self.ping_lock = threading.Lock()
        self.clear_stats()

    def clear_stats(self):
        # counters
        if self.ping_lock.acquire():
            self.ping_sent = 0
            self.ping_recv = 0
            self.ping_late = 0
            self.ping_lock.release()

    def pktloss(self):
        if self.ping_sent == 0:
            return 0
        if self.ping_lock.acquire():
            pktloss = self.ping_recv / self.ping_sent * 100.0
            self.ping_lock.release()
        return pktloss

    def _process_data(self, conn, message):
        '''the SpreadPingListener's _process_data() method intercepts any self-directed
        messages which are self-pings and processes the ping callback.  If the message
        is not a self-ping, it is not intercepted and instead is passed up to the handle_data()
        method.'''
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
                self.logger.debug('Late ping (id=%s) discarded because it already timed out.' % (ping_id))
                return
            if self.ping_lock.acquire(): # always true, and blocks
                (ping_cb, send_time, timeout) = self.ping_callbacks.pop(ping_id)
                self.ping_recv += 1
                self.ping_lock.release()
            try:
                ping_cb (True, elapsed)
            except:
                self.logger.critical('User ping callback threw an exception.')
                print_tb(self.logger, 'PingListener ping callback') # logs traceback
            return
        # otherwise, just handle this as a regular data message
        try:
            self.handle_data(conn, message)
        except:
            print_tb(self.logger, 'SpreadPingListener handle_data')

    def handle_timer(self, conn):
        '''Ping expiration happens here.
        This is now thread safe'''
        pending_pings = len(self.ping_callbacks)
        if pending_pings == 0:
            return
        timeouts = []
        now = time.time()
        if self.ping_lock.acquire(): # always true, block, get the lock...
            try:
                dict_iter = self.ping_callbacks.iteritems
            except:
                dict_iter = self.ping_callbacks.items
            for ping_id, cb_items in dict_iter():
                (timer_cb, time_sent, timeout) = cb_items
                expire = time_sent + timeout
                if now >= expire:
                    self.logger.debug('Expiring ping id %d because now %.4f is > expire %.4f' % (ping_id, now, expire))
                    timeouts.append(ping_id)
            self.ping_lock.release() # end of lock...
        for ping_id in timeouts:
            (user_cb, time_sent, timeout) = self.ping_callbacks.pop(ping_id)
            elapsed = now - time_sent
            try:
                user_cb(False, elapsed)
            except:
                self.logger.warning('Exception in timer handler when invoking user timer callback.')
                print_tb(self.logger, 'PingListener user ping callback')# logs traceback

    def ping(self, conn, callback, timeout=30):
        payload = 'PING:%d:%.8f'
        if self.ping_lock.acquire(): # always true, and blocks
            this_id = self.ping_id
            self.ping_id += 1
            payload = payload % (this_id, time.time())
            mesg_type = self.ping_mtype
            self.ping_callbacks[this_id] = (callback, time.time(), timeout)
            self.ping_sent += 1
            self.ping_lock.release()
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
    def __init__(self, cb_conn=None, cb_data=None, cb_dropped=None, cb_error=None, cb_unk_group=None):
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
        self.cb_unk_group = cb_unk_group
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

    def _safe_cb(self, cb, args):
        try:
            cb(*args)
        except:
            print_tb(self.logger, 'GroupCallbackListener._safe_cb(%s)' % (cb)) # logs traceback

    # this function avoids a lot of boilerplate here, should also catch exceptions perhaps
    def _invoke_cb(self, group, callback, args):
        gcb = self.cb_groups.get(group, None)
        if gcb:
            cb_ref = getattr(gcb, callback)
            if cb_ref:
                try:
                    cb_ref(*args)
                    return True
                except:
                    print_tb(self.logger, 'GroupCallbackListener._invoke_cb(%s on group %s)' % (callback, group)) # logs traceback
        return False

    def handle_data(self, conn, message):
        args = (self, conn, message)
        if self.cb_data:
            self._safe_cb(self.cb_data, args)
        groups = message.groups
        found_group = False
        for group in groups:
            if self._invoke_cb(group, 'cb_data', (conn, message)):
                found_group = True
        if self.cb_unk_group and not found_group:
            self._safe_cb(self.cb_unk_group, args)

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

    def join_with_wait(self, conn, group, timeout=15):
        '''Join group, and return when the join was successfully joined, or if the timeout expired.
        This will block up to C<timeout> seconds.
        For nonthreaded usage, this method needs to result in a loop that causes poll() to be hit repeatedly so
        asyncore gets some time to do network IO.
        For threaded usage, this method should just sleep.  (Though it should abort early if the connection is lost...)
        '''
        expire_time = time.time() + timeout
        joined = False
        members = []
        def _done(conn, group, membership):
            joined = True
            members = membership
            self.logger.debug('Internal closure group joined callback invoked! Group "%s" joined! Members: %s' % (group, members))
        self.set_group_cb(group, GroupCallback(cb_start=_done))
        conn.join(group)
        while not joined and time.time() < expire_time:
            conn.run(count=10, timeout=0.1) # should work in threaded and non-threaded code just fine
            print (('waiting for join to group "%s"' % group))
            time.sleep(0.1)
        return joined

class DebugListener(SpreadListener):
    '''some verbose logging to debug level on various events'''

    def handle_connected(self, conn):
        self.logger.debug('DEBUG: Got connected, new session is ready!')

    def handle_dropped(self, conn):
        self.logger.debug('DEBUG: Lost connection!')

    def handle_error(self, conn, exc):
        self.logger.debug('DEBUG: Got error! Exception:%s, %s' % (type(exc), exc))

    def handle_data(self, conn, message):
        self.logger.debug('DEBUG: Received message:%s' % message)

    def handle_group_start(self, conn, group, membership):
        self.logger.debug('DEBUG: New Group Joined:%s  Members:%s' % (group, membership))

    def handle_group_trans(self, conn, group):
        self.logger.debug('DEBUG: Transitional message received, not much actionable here. Group:%s' % group)

    def handle_group_end(self, conn, group, old_membership):
        self.logger.debug('DEBUG: Group no longer joined:%s  Old membership:%s' % (group, old_membership))

    def handle_group_join(self, conn, group, member, cause):
        self.logger.debug('DEBUG: Group Member Joined group:%s  Member: %s  Cause:%s' % (group, member, cause))

    def handle_group_leave(self, conn, group, member, cause):
        self.logger.debug('DEBUG: Group Member Left group:%s  Member:%s  Cause:%s' % (group, member, cause))

    def handle_network_split(self, conn, group, changes, old_membership, new_membership):
        self.logger.debug('DEBUG: Network Split event, group:%s Number changes:%d  Old Members:%s New members:%s' % (group, changes, old_membership, new_membership))

    def handle_timer(self, conn):
        self.logger.debug('DEBUG: Timer tick...')
        # now invoke any parent class handle_timer() method too
        try:
            super(DebugListener, self).handle_timer(conn)
        except:
            self.logger.warning('DEBUG: Parent class threw an exception in handle_timer()')
            print_tb(self.logger, 'DebugListener handle_timer user callback') # log traceback

