'''AsyncSpread connection module, contains AsyncSpread and AsyncSpreadThreaded classes'''
import socket, struct, copy, asyncore, asynchat, time, logging, sys, threading, traceback, itertools
from collections import deque
from message import *
from services import *
from listeners import *
from expt import *


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
    def emit(self, record):
        '''do nothing handler'''
        pass

# This happens at import-time.  I think it's polite.
logging.getLogger().addHandler(NullLogHandler())

def print_tb(logger):
        (exc_type, exc_val, tback) = sys.exc_info()
        logger.warning('handle_error(): Got exception: %s' % exc_val)
        logger.info('Traceback: ' + traceback.format_exc())
        sys.exc_clear()

class AsyncChat26(asynchat.async_chat):
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

def _unpack_header(payload):
    '''used for python < 2.5 where the struct module doesn't offer the
    more optimized struct.Struct class for holding pre-compiled struct formats.'''
    return struct.unpack(SpreadProto.HEADER_FMT, payload)

def make_unpack_header():
    '''optimization helper to return a method that will unpack spread headers using Struct.unpack.
    On python 2.5+ it will return a precompiled struct.Struct() object's bound unpack method,
    and on python 2.4 it returns the local method _unpack_header() instead'''
    try:
        precompiled = struct.Struct(SpreadProto.HEADER_FMT)
        return precompiled.unpack # bound method
    except: # python <= 2.4 support
        return _unpack_header

class AsyncSpread(AsyncChat26): # was asynchat.async_chat
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
                 reconnect=False, # TODO: implement this
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
        AsyncChat26.__init__(self, map=self.my_map)
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
        self.unpack_header = make_unpack_header()
        self.logger = logging.getLogger()
        self.proto = SpreadProto()
        self.mfactory = None
        self._clear_ibuffer()
        # holds private session name given by server on successful connection:
        self.session_name = None
        #
        self.msg_count = 0
        # timer interval and initialization
        self.timer_interval = timer_interval
        self._reset_timer()
        # state machine for protocol processing uses these:
        self.need_bytes = 0
        self.next_state = None
        # more settings (is conn dead?)
        self.dead = False
        # new events for threaded signalling:
        self.session_up = threading.Event()
        # more connection state, reconnect flag:
        self.do_restart = threading.Event()
        # more connection state, want shutdown:
        self.shutdown = False
        # handle startup connection
        if start_connect:
            self.start_connect()

    def __str__(self): # TODO: remove self.dead and self.shutdown from this!
        return '<%s>: name="%s", connected=%s, server="%s:%d", session_name="%s", d/s=%s/%s' % (self.__class__,
                                                                                                self.name, self.connected, self.host, self.port, self.session_name, self.dead, self.shutdown)

    def _do_connect(self):
        '''perform actual socket connect() to server'''
        self.do_restart.clear()
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
        self.connect((self.host, self.port))

    def is_connected(self):
        return self.session_up.isSet()

    def start_connect(self, timeout=10):
        '''invoke this to begin the connection process to the server'''
        if self.connected:
            return True
        self._do_connect()
        return self.wait_for_connection(timeout)

    def wait_for_connection(self, timeout, sleep_delay=0.1):
        '''Spend time in self.poll() until the timeout expires, or we are connected, whichever first.
        Return boolean indicating if we are connected yet.  Or not.'''
        time_end = time.time() + timeout
        # TODO: check to make sure the connection succeeds too, and that we dont want to shut down
        while not self.is_connected() and time.time() < time_end:
            print 'Waiting for session_up to be set()...'
            if self.dead or self.shutdown: # maybe dead _is_ shutdown?
                return False
            self.poll(timeout/100)
            time.sleep(sleep_delay)
        print 'wait_for_connection() returning'
        return self.is_connected()

    def poll(self, timeout=0.001, count=1):
        '''spend time on the socket layer (asyncore.loop), looking for IO, invoking IO handlers'''
        if True:# not self.dead:
            asyncore.loop(timeout=timeout, count=count, use_poll=True, map=self.my_map)
        if self._is_timer():
            self.listener._process_timer(self)

    def run(self, timeout=0.1, count=None):
        '''spend more time than poll() doing IO on the connection'''
        main_loop = 0
        #print 'TIMEOUT is now:', timeout, 'COUNT is:', count
        while not self.shutdown and (count is None or main_loop <= count):
            main_loop += 1
            #print 'POLL! timeout:', timeout, 'main_loop:', main_loop
            self.poll(timeout)

    def set_level(self, level):
        '''totally delegated to internal SpreadProto object'''
        self.proto.set_level(level)

    def _clear_ibuffer(self):
        '''clears internal input buffer and buffer offset'''
        self._ibuffer = ''
        self._ibuffer_start = 0

    def _reset_timer(self, delay=None):
        '''clear the local timer and reset it to the next scheduled time, using delay'''
        if delay is None:
            delay = self.timer_interval
        self.timer_next = time.time() + delay

    def _is_timer(self):
        '''method to check the timer and either return True (and reset the timer) or return
        False if the timer isn't due yet.'''
        now = time.time()
        if now >= self.timer_next:
            self._reset_timer()
            return True
        return False

    def handle_close(self):
        '''invoked by asyncore when the socket is closed from the server side.'''
        self.logger.warning('Connection lost to server: %s:%d' % (self.host, self.port))
        self.dead = True
        self.session_name = None
        self.mfactory = None
        self.close()
        self.listener._process_dropped(self)
        self.session_up.clear()

    def handle_error(self):
        '''invoked when an error happens on the socket (unexpected error) or an unhandled
        exception occurs in an IO handler.'''
        (exc_type, exc_val, tback) = sys.exc_info()
        print_tb(self.logger)
        self.listener._process_error(self, exc_val)
        self._drop()
        self.listener._process_dropped(self)
        self.session_up.clear()

    def handle_connect(self):
        '''invoked by asyncore when connect() returns a successful socket connection to the server'''
        self.mfactory = SpreadMessageFactory()
        self.logger.debug('handle_connect(): got TCP connection to server, sending credentials')
        connect_msg = SpreadProto.protocol_connect(self.name, self.membership_notifications, self.priority_high)
        self.wait_bytes(1, self.st_auth_read)
        self.push(connect_msg)

    def _drop(self):
        '''internal function to close and clear all state associated with a connection'''
        self.dead = True
        self.close() # changes self.connected to False, usually
        self.discard_buffers()
        self._clear_ibuffer()
        if self.connected:
            #self.logger.warning('WARNING: _drop() found self.connected = True and just set it to False!')
            self.connected = False
        self.session_name = None
        self.session_up.clear()

    def _send(self, data):
        '''internal method to abstract the difference between threaded and non-threaded enqueue methods.
        in non-threaded use, this just invokes the asyncore.dispatcher's push() method, but in threaded usage
        it actually pushes onto a thread-safe deque instead'''
        self.push(data)

    def _dispatch(self, message):
        '''when a complete SpreadMessage is received, this method will invoke the Listener's appropriate methods to
        deliver the message according to its type.'''
        listener = self.listener
        if listener is None:
            return
        # Listeners should not throw exceptions here
        if isinstance(message, DataMessage):
            listener._process_data(self, message)
        elif isinstance(message, MembershipMessage):
            listener._process_membership(self, message)
        elif isinstance(message, OpaqueMessage):
            # let's hope this never happens
            self.logger.critical('Unknown message received (and dropped) as OpaqueMessage: %s' % (message))
        else:
            # this never happens. assert here
            assert message, 'Code error! Unexpected type of message: %s' % (type(message))

    def collect_incoming_data(self, data):
        '''Buffer the data'''
        self._ibuffer += data

    def found_terminator(self):
        '''invoked by asyncore.asynchat when the terminating condition has been met, which
        is after a fixed number of bytes (produced by the protocol state machine) has been read'''
        data = self._ibuffer[self._ibuffer_start:(self._ibuffer_start+self.need_bytes)]
        self._ibuffer_start += self.need_bytes
        if len(self._ibuffer) > 500: # TODO: remove hard coded value here
            self._ibuffer = self._ibuffer[self._ibuffer_start:]
            self._ibuffer_start = 0
        next_cb = self.next_state
        next_cb(data)

    def wait_bytes(self, need_bytes, next_state):
        '''used by the protocol state machine to indicate that after *need_bytes* have been received,
        to invoke *next_state* to continue processing.  Every state must set its next_state, using this method.'''
        need_bytes = int(need_bytes) # py 2.4 fixup for struct.unpack()'s longs not satisfying isinstance(int)
        self.need_bytes = need_bytes
        self.next_state = next_state
        self.set_terminator(need_bytes)

    def st_auth_read(self, data):
        '''protocol state: this method handles decoding the length of the authentication string that is to follow'''
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
        '''protocol state: this method parses the authentication methods string, which is a space delimited list
        usually "NULL " but it may be: "NULL IP" or "IP ".  There is trailing whitespace usually.'''
        self.logger.debug('STATE: st_auth_process')
        methods = data.rstrip().split(' ') # space delimited?
        if 'NULL' not in methods: # TODO: add 'IP' support at some point
            self.logger.critical('Spread server does not accept our NULL authentication. Server permited methods are: "%s"' % (data))
            self._drop()
            self.listener._process_error(self, SpreadAuthException('auth rejected'))
            return
        msg_auth = SpreadProto.AUTH_PKT
        self.wait_bytes(1, self.st_read_session)
        self.push(msg_auth)
        return

    def st_read_session(self, data):
        '''protocol state: this method reads the authentication result code, which is a single signed byte
        and is the value 1 for success or a negative value mapping to some error condition.  if authentication
        fails, the listener's _process_error() is invoked with a SpreadException as an argument! Neat.'''
        self.logger.debug('STATE: st_read_session')
        (accept,) = struct.unpack('b', data)
        if accept != 1:
            self.logger.critical('Failed authentication / connection: %s' % (accept))
            self._drop()
            self.listener._process_error(self, SpreadException(accept))
            return
        self.wait_bytes(3, self.st_read_version)

    def st_read_version(self, data):
        '''protocol state: this reads the 3 byte version data, and requires that the values are not (-1, -1, -1),
        which I'm not sure ever happens.'''
        self.logger.debug('STATE: st_read_version')
        (major_version, minor_version, patch_version) = struct.unpack('bbb', data)
        self.logger.info('Server reports it is Spread version: %d.%d.%d' % (major_version, minor_version, patch_version))
        version = (major_version | minor_version | patch_version)
        if version == -1: # when does this happen?
            self._drop()
            self.listener._process_error(self, SpreadException(version))
            return
        self.server_version = (major_version, minor_version, patch_version)
        self.wait_bytes(1, self.st_read_session_namelen)

    def st_read_session_namelen(self, data):
        '''protocol state: this reads the length of the session name string that the server is
        assigning to this client's connection.  If the length is -1, then the connection has failed in some way.'''
        self.logger.debug('STATE: st_read_session_namelen')
        (group_len,) = struct.unpack('b', data)
        if group_len == -1:
            self._drop()
            self.listener._process_error(self, SpreadException(group_len))
            return
        self.wait_bytes(group_len, self.st_set_session)

    def st_set_session(self, data):
        '''protocol state: this reads the string for the client's "session_name" for this connection,
        which is the unique identifier that this client has for itself for the lifetime of this connection.
        It is usually in the format: '#my_private_name#server_name' where my_private_name is
        supplied by the client, and server_name is the unique name of this spread daemon.'''
        self.logger.debug('STATE: st_set_session')
        self.session_name = data
        self.wait_bytes(48, self.st_read_header)
        self.logger.info('Spread session established to server:  %s:%d' % (self.host, self.port))
        self.logger.info('My private session name for this connection is: "%s"' % (self.session_name))
        self.session_up.set() # hmm, set session_up BEFORE or AFTER calling listener's handle_connected() method?
        self.listener._process_connected(self)

    def st_read_header(self, data):
        '''protocol state: this decodes the 48-byte header of every SpreadMessage, extracting the
        per-message: service type (reliability level), sender name, number of groups this message is
        addressed to, numeric 16-bit message type as set by the sender application,  and the length of
        the payload (mesg_len).  If the number of groups is > 0 (usually it is), then the next state reads
        the length prefixed list of destination groups.  Otherwise, the message payload is read.

        TODO: handle endianness differences properly here.
        '''
        self.logger.debug('STATE: st_read_header')
        (svc_type, sender, num_groups, mesg_type, mesg_len) = self.unpack_header(data)
        # TODO: add code to flip endianness of svc_type and mesg_type if necessary (independently?)
        endian_test = 0x80000080
        endian_wrong = (svc_type & endian_test) == 0
        svc_type &= ~endian_test
        mesg_type &= ~endian_test
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
        '''protocol state: this reads the list of destination groups that this message is addressed to.
        Note that group strings are fixed-length at 32 byte strings each, so the decoding is
        straightforward.  The ASCII NULL value is not permitted in group names, and is used as a terminator
        byte when the group strings are parsed out.  If there is no message body (mesg_len==0) then
        the message is fully decoded and this method invokes _dispatch() to pass the completed message
        to the listener.'''
        self.logger.debug('STATE: st_read_groups')
        group_packer = SpreadProto.GROUP_FMTS[self.mfactory.num_groups] # '32s' * len(gname)
        groups_padded = struct.unpack(group_packer, data)
        groups = [ g[0:g.find('\x00')] for g in groups_padded ] # trim out nulls
        factory_mesg = self.mfactory.process_groups(groups)
        mesg_len = self.mfactory.mesg_len
        if mesg_len > 0:
            self.wait_bytes(mesg_len, self.st_read_message)
            return
        # handle case of no message body, on self-leave
        self.wait_bytes(48, self.st_read_header)
        self._dispatch(factory_mesg)

    def st_read_message(self, data):
        '''protocol state: this method processes the message payload, and uses _dispatch() to
        pass the completed message up to the listener.'''
        self.logger.debug('STATE: st_read_message')
        self.msg_count += 1
        factory_mesg = self.mfactory.process_data(data)
        self.wait_bytes(48, self.st_read_header) # always going to a new message next
        self._dispatch(factory_mesg)

    def join(self, group):
        '''join a group, by sending the JOIN request to the server.  If the connection is not up or has failed,
        this method will raise a SpreadException.  If this method returns, it always returns True.'''
        if not self.is_connected():
            self.logger.critical('Not connected to spread. Cannot join group "%s"' % (group))
            raise SpreadException('not connected') # not connected
        join_msg = SpreadProto.protocol_create(SpreadProto.JOIN_PKT, 0, self.session_name, [group], 0)
        self._send(join_msg)
        return True

    def leave(self, group):
        '''leave a group, by sending the LEAVE request to the server.  If the connection is not up or has failed,
        this method will return False.  Otherwise, it returns True.'''
        if not self.is_connected():
            self.logger.critical('No session established with server... Failed leave() message')
            return False
        leave_msg = SpreadProto.protocol_create(SpreadProto.LEAVE_PKT, 0, self.session_name, [group], 0)
        self._send(leave_msg)
        return True

    def _do_disconnect(self):
        self._drop() # non-threaded action here can touch the socket

    def disconnect(self):
        '''gracefully disconnect from the server, by sending a KILL (self) request to the server.  If the connection
        is not up, or has already been closed, this method returns False.  Otherwise it returns True.'''
        if not self.is_connected():
            return False # is we're not connected, just return False instead of raising an exception
        who = self.session_name
        disco_msg = SpreadProto.protocol_create(SpreadProto.KILL_PKT, 0, who, [who], 0)
        self._send(disco_msg)
        self.shutdown = True
        self._do_disconnect()
        return True

    def multicast(self, groups, message, mesg_type, self_discard=True):
        '''Send a message to all members of a group.  If the connection is not up, a SpreadException
        is raised to the caller.  This method returns True (when no exception is raised).

        @param groups: group list (string)
        @type groups: list
        @param message: data payload
        @type message: string
        @param mesg_type: numeric message type, must fit in 16 bits
        @type mesg_type: int (short int)
        @param self_discard: set to True to stop server from reflecting message back to me
        @type self_discard: bool
        '''
        if not self.is_connected():
            self.logger.critical('Not connected to spread. Cannot send multicast message to group(s) "%s"' % (groups))
            raise SpreadException('no connection')
        #print 'multicast(groups=%s, message=%s, mesg_type=%d, self_discard=%s)' % (groups, message, mesg_type, self_discard)
        data_len = len(message)
        svc_type_pkt = self.proto.get_send_pkt(self_discard)
        header = SpreadProto.protocol_create(svc_type_pkt, mesg_type, self.session_name, groups, data_len)
        pkt = header + message
        self._send(pkt)
        return True

    def unicast(self, group, message, mesg_type):
        '''Send a message to a single group or client.

        This is an alias for sending to a single destination, and sets the SELF_DISCARD to False,
        so if you unicast() a message to yourself, or to a group you are a member of, you will
        receive a copy of that message.  To turn on self_discard in those cases, use multicast()
        instead of unicast() and pass it a list of a single group, and set self_discard=True.'''
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
        self.io_thread = None
        # more settings
        if start_connect:
            self.do_restart.set()
        # outbound messages for threaded uses
        self.out_queue = deque()
        # handle startup
        self.start_io_thread()
        if start_connect:
            self.start_connect()

    def _send(self, pkt):
        '''threaded version of _send() which uses a deque() object as a thread-safe queue'''
        self.out_queue.append(pkt)

    def start_io_thread(self):
        print 'Starting IO thread'
        name_str = 'AsyncSpreadThreaded I/O Thread: %s' % (self.name)
        thr = threading.Thread(target=self.do_io, args=[name_str], name=name_str)
        thr.daemon = True
        thr.start()
        self.io_thread = thr

    def start_connect(self, timeout=10):
        '''initiate the connection process.  returns True/False after the connection is made or the timeout expires'''
        print 'start_connect() invoked!'
        if self.is_connected():
            return True
        self.do_restart.set()
        print 'start_connect() timeout:', timeout
        return self.wait_for_connection(timeout)

    def wait_for_connection(self, timeout):
        '''wait up to C{timeout} seconds for connection to be completed.'''
        print 'wait_for_connection(): Waiting up to %0.3f seconds for session_up to be set()' % (timeout)
        self.session_up.wait(timeout)
        return self.is_connected()

    def do_io(self, thr_name):
        '''This is the main IO thread's main loop for threaded asyncspread usage...  It
        looks for new data to send from the output queues and checks the socket for
        new messages, and invokes response callbacks through the listener object.

        If the connection is shut down, this thread will wait until do_restart is set to
        True, and initiate a new connection.  I think.
        '''
        print '%s>> Doing io in do_io()' % (thr_name)
        main_loop = 0
        while not self.shutdown:
            main_loop += 1
            self.poll(0.01)
            if self.is_connected():
                # deliver queued up outbound messages
                while len(self.out_queue) > 0 and not self.shutdown:
                    self.push(self.out_queue.popleft())
            else:
                # check to see if we want to restart the connection here:
                if self.do_restart.isSet():
                    self._do_connect() # clears do_restart
                    #self.run(timeout=0.1, count=5)
                    self.poll(timeout=0.1, count=10)
                else:
                    self.do_restart.wait(0.5)
        print '\n%s>> IO Thread exiting' % (thr_name)
        print 'Myself:', self
        self._drop()
        # set self.io_thread to None?
        # self.io_thread = None

    def _do_disconnect(self):
        '''invoked by threaded version from inside disconnect() by a user thread,
        i.e. NOT the IO thread.

        since the self.shutdown bool flag is set in disconnect(), this method doesn't have to
        do anything, since that will trigger the do_io() loop to terminate, and self._drop() will
        then be called.
        '''
        pass
