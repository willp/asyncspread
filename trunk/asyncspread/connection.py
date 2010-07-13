#!/usr/bin/env python
import socket, struct, copy, asyncore, asynchat, time, logging, sys, threading, traceback, itertools
from collections import deque
from message import *
from services import *
from listener import *

__version__ = '0.1.3a' # used by setup.py

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
    '''Asynchronous client API for Spread 4.x group messaging written in pure Python.

    AsyncSpread's features are:

    * asynchronous client API to Spread 4.x message broker, built using only python standard
    library modules, including asyncore

    * non-threaded and threaded support, up to the user's choice

    * messaging API supporting multicast (one:many) and unicast (one:one) style messaging among clients

    * flexible API for receiving messages and notifications, based on a SpreadListener class that may be
    subclassed to override default behavior, or use the supplied GroupCallback listener which lets you
    easily wire up your methods as callbacks to be invoked when certain Group messages or events arrive.

    * supports a built-in SpreadPingListener class to support a ping() test of the server, using a special
    message addressed to one's self, sent through the server and handled automatically (with configurable
    timeout)

    * and much more!
    ''' # docstring used by setup.py
    def __init__(self, name, host, port,
                 listener=None,
                 membership_notifications=True,
                 priority_high=False,
                 timer_interval=1.0,
                 keepalive=True,
                 start_connect=False,
                 map=None):
        '''Asynchronous connection to a spread daemon, non-threaded, based on asyncore.asynchat

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
        self.session_name = None
        self.msg_count = 0
        # deal with timer:
        self.timer_interval = timer_interval
        self._reset_timer()
        # more settings
        self.dead = False
        # state machine for protocol processing uses these
        self.need_bytes = 0
        self.next_state = None
        # thread/io data
        self.io_active = False # TODO: thread only
        self.io_ready = threading.Event() # TODO: thread only
        self.do_reconnect = False
        self.shutdown = False
        # handle startup connection
        if start_connect:
            self.start_connect()

    def __str__(self): # TODO: remove self.dead and self.shutdown from this!
        return '<%s>: name="%s", connected=%s, server="%s:%d", session_name="%s", dead=%s, shutdown=%s' % (self.__class__, self.name, self.connected, self.host, self.port, self.session_name, self.dead, self.shutdown)

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
        if self.connected:
            print 'WARNING: ALREADY CONNECTED!'
            return True
        print 'start_connect() timeout:', timeout
        self._do_connect()
        return self.wait_for_connection(timeout)

    def wait_for_connection(self, timeout=10, sleep_delay=0.1):
        '''Spend time in self.poll() until the timeout expires, or we are connected, whichever first.
        Return boolean indicating if we are connected yet.  Or not.'''
        time_end = time.time() + timeout
        while self.session_name is None and time.time() < time_end:
            print 'Waiting for connection...'
            if self.dead or self.shutdown:
                return False
            self.poll(timeout/100)
            time.sleep(sleep_delay)
        print 'wait_for_connection() returning. session_name:', self.session_name
        return self.session_name is not None

    def poll(self, timeout=0.001):
        if not self.dead:
            asyncore.loop(timeout=timeout, count=1, use_poll=True, map=self.my_map)
        if self._is_timer():
            self.listener._process_timer(self)
        return not self.dead

    def loop(self, timeout=None, slice=0.1):
        '''factor out expire_every into a generalized timer that calls up into listener'''
        if self.io_active:
            print 'ERROR: using loop() at same time as background IO thread is not valid.'
            raise IOError('Cannot do asyncore IO in two different threads')
        main_loop = 0
        timeout = timeout / slice
        print 'TIMEOUT is now:', timeout
        while not self.dead and (timeout is None or main_loop <= timeout):
            main_loop += 1
            print 'POLL! slice:', slice, 'main_loop:', main_loop
            self.poll(slice)


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
        self._ibuffer = ''
        self._ibuffer_start = 0

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
        connect_msg = SpreadProto.protocol_connect(self.name, self.membership_notifications, self.priority_high)
        self.wait_bytes(1, self.st_auth_read)
        self.push(connect_msg)

    def handle_close(self):
        self.logger.warning('Connection lost to server: %s:%d' % (self.host, self.port))
        self.dead = True
        self.session_name = None
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
        self.close() # changes self.connected to False, usually
        self.discard_buffers()
        self._clear_ibuffer()
        if self.connected:
            self.logger.warning('WARNING: _drop() found self.connected = True and just set it to False!')
            self.connected = False
        self.session_name = None

    def _send(self, data):
        self.push(data)

    def _dispatch(self, message):
        listener = self.listener
        if listener is not None:
            # Listeners should not throw exceptions here
            if isinstance(message, DataMessage):
                listener._process_data(self, message)
            elif isinstance(message, MembershipMessage):
                listener._process_membership(self, message)
            elif isinstance(message, OpaqueMessage):
                # let's hope this never happens
                self.logger.critical('Unknown message received (and ignored) as OpaqueMessage: %s' (message))
            else:
                # this never happens. assert here
                assert message, 'Code error! Unexpected type of message: %s' % (type(message))

    def collect_incoming_data(self, data):
        '''Buffer the data'''
        self._ibuffer += data

    def found_terminator(self):
        data = self._ibuffer[self._ibuffer_start:(self._ibuffer_start+self.need_bytes)]
        self._ibuffer_start += self.need_bytes
        if len(self._ibuffer) > 500: # TODO: remove hard coded value here
            self._ibuffer = self._ibuffer[self._ibuffer_start:]
            self._ibuffer_start = 0
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
        self.wait_bytes(1, self.st_read_session_namelen)

    def st_read_session_namelen(self, data):
        self.logger.debug('STATE: st_read_session_namelen')
        (group_len,) = struct.unpack('b', data)
        if group_len == -1:
            self._drop()
            self.listener._process_error(self, SpreadException(group_len))
            return
        self.wait_bytes(group_len, self.st_set_session)

    def st_set_session(self, data):
        self.logger.debug('STATE: st_set_session')
        self.session_name = data
        self.logger.info('Spread session established to server:  %s:%d' % (self.host, self.port))
        self.logger.info('My private session name for this connection is: "%s"' % (self.session_name))
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
        if self.session_name is None:
            self.logger.critical('Not connected to spread. Cannot join group "%s"' % (group))
            raise SpreadException(100) # not connected
        join_msg = SpreadProto.protocol_create(SpreadProto.JOIN_PKT, 0, self.session_name, [group], 0)
        self._send(join_msg)
        return True

    def leave(self, group):
        if self.session_name is None:
            self.logger.critical('No session established with server... Failed leave() message')
            return False
        leave_msg = SpreadProto.protocol_create(SpreadProto.LEAVE_PKT, 0, self.session_name, [group], 0)
        self._send(leave_msg)
        return True

    def disconnect(self):
        if self.session_name is None:
            return False # is we're not connected, just return False instead of raising an exception
        who = self.session_name
        disco_msg = SpreadProto.protocol_create(SpreadProto.KILL_PKT, 0, who, [who], 0)
        self._send(disco_msg)
        self.poll()
        self.shutdown = True
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
        if self.session_name is None:
            self.logger.critical('Not connected to spread. Cannot send multicast message to group(s) "%s"' % (groups))
            raise SpreadException(100)
        #print 'multicast(groups=%s, message=%s, mesg_type=%d, self_discard=%s)' % (groups, message, mesg_type, self_discard)
        data_len = len(message)
        svc_type_pkt = self.proto.get_send_pkt(self_discard)
        header = SpreadProto.protocol_create(svc_type_pkt, mesg_type, self.session_name, groups, data_len)
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
        kwargs['map'] = dict() # ensure all instances get their own distinct map object, to prevent asyncore from exploding
        self.my_map = kwargs['map']
        # pull start_connect param out, and be sure superclass sees it as False, to avoid non-threaded
        # I know this is a bit overkill...
        start_connect = kwargs.get('start_connect', False)
        kwargs['start_connect'] = False
        # invoke superclass
        AsyncSpread.__init__(self, *args, **kwargs)
        print 'NonThreaded constructor done, Threaded stuff happening now in AsyncSpreadThreaded'
        # Threading related concurrency controls
        self.io_thread_lock = threading.Lock()
        self.io_thread = None
        # more settings
        self.do_reconnect = True
        # outbound messages for threaded uses
        self.out_queue = deque()
        # handle startup
        if start_connect:
            self.start_connect()

    def _send(self, pkt):
        self.out_queue.append(pkt)

    def start_io_thread(self):
        '''This is now thread-safe
        1. obtain lock on io_thread_lock (BLOCKING)
        2. check self.io_thread is None
        3. if False, start thread and set True
        4. else release lock and return
        '''
        self.io_thread_lock.acquire() # blocking
        if self.io_thread is None:
            self.io_ready.clear()
            name_str = 'AsyncSpreadThreaded I/O Thread: %s' % (self.name)
            thr = threading.Thread(target=self.do_io, args=[name_str], name=name_str)
            thr.daemon=True
            thr.start()
            self.io_thread = thr
        self.io_thread_lock.release()
        return

    def start_connect(self, timeout=10):
        self.do_reconnect = True
        print 'start_connect() timeout:', timeout
        return self.wait_for_connection(timeout)

    def wait_for_connection(self, timeout=10):
        '''If io thread is not started, start it.
        Then wait up to timeout seconds for connection to be completed.'''
        if self.io_thread is None:
            print 'wait_for_connection(): really firing up IO thread'
            self.start_io_thread()
        print 'wait_for_connection(): Waiting up to %0.3f seconds for io_ready to be set()' % (timeout)
        self.io_ready.wait(timeout)
        is_connected = self.session_name is not None
        return is_connected

    def do_io(self, thr_name):
        '''This is the main IO thread's main loop for threaded asyncspread usage...  It
        looks for new data to send from the output queues and checks the socket for
        new messages, and invokes response callbacks through the listener object.

        If the connection is shut down, this thread will wait until reconnect is set to
        True, and initiate a new connection.  I think.

        This logic is insane.  Needs MAJOR help / refactoring.
        '''
        me = threading.local() # This isn't really used yet
        me.thr_name = thr_name
        print '%s>> Doing io in do_io()' % (thr_name)
        main_loop = 0
        while not self.shutdown:
            main_loop += 1
            # handle timer
            if self._is_timer():
                self.listener._process_timer(self)
            # handle reconnect
            if self.do_reconnect and not self.session_name:
                self.do_reconnect = False # reset flag
                print 'IO thread trying to self._do_connect()...  reset do_reconnect to False'
                self._do_connect()
                continue
            if not self.dead:
                #self.poll() # could be outside this test.
                asyncore.loop(timeout=0.01, count=2, use_poll=True, map=self.my_map)
                # make sure not to deliver any messages if the session isn't ready
                if self.session_name:
                    # deliver queued up outbound data
                    while len(self.out_queue) > 0 and not self.shutdown:
                        self.push(self.out_queue.popleft())
            else:
                # need to do something non-CPU intensive here
                time.sleep(0.5)
        print '%s>> IO Thread exiting' % (thr_name)
        self._drop()
        # set self.io_thread to None?
        # self.io_thread = None

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
