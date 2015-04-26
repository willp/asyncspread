![http://nuclei.com/asyncspread/AsyncSpread_sm3.png](http://nuclei.com/asyncspread/AsyncSpread_sm3.png)

A Python client API for the Spread 4.x group messaging system.

# Architecture #

Overall, the architecture consists of several classes:
  * AsyncSpread - asynchronous connection and protocol handlers
  * SpreadProto, ServiceTypes - non-instantiated container classes for protocol specific parameters and encoded strings
  * SpreadMessage - base class for all messages received from a Spread daemon
  * MembershipMessage - base class for membership notification messages
  * JoinMessage, LeaveMessage, DisconnectMessage, TransitionalMessage, NetworkMessage - specific MembershipMessage variants, actually instantiated
  * DataMessage - messages sent by other Spread clients, with payload and "mesg\_type" hint
  * SpreadMessageFactory - builds different SpreadMessage objects based on message headers
  * SpreadListener - base class for all listeners, its methods invoked by protocol events
  * SpreadPingListener - listener that implements a ping() send and handle\_ping() response with user callbacks
  * CallbackListener - listener that will route callbacks to group-specific callbacks and/or connection level events to conenction-level callbacks, does not require user to define any new subclasses or use inheritance at all.
  * SpreadException - a one-size-fits-all exception object for errors returned by the Spread daemon


AsyncSpread is a subclass of the asynchat.async\_chat, which implements the wire-protocol of Spread 4.x using asynchronous event processing on a TCP socket connected to a Spread daemon.  One instance of the AsyncSpread class is one connection to a Spread network.

To use AsyncSpread, you first subclass a listener class, like SpreadPingListener and override any or all of the "handle_" methods.  These methods include:
  * handle\_authenticated() called when session is totally "up" (uses NULL authentication)
  * handle\_connect() called when socket connect() completes successfully or not, but is not useful. Ignore this one.
  * handle\_error() called with an exception object whenever any error happens, network or protocol
  * handle\_dropped() called if the connection to the server is dropped
  * handle\_data() called with a DataMessage, whenever you get a message!  Most handy.
  * handle\_group\_start() called when you have joined a new group
  * handle\_group\_join() called when someone joins a group you are on, for any reason
  * handle\_group\_leave() called when someone leaves a group you are on, for any reason
  * handle\_group\_end() called when you get confirmation from the server on leaving a group
  * handle\_network\_split() called when a group is split due to a spread-to-spread network or host issue, provides the old and new membership lists and the size of the delta (positive or negative)
  * handle\_group\_trans() called when the server sends a "transitional" membership message, not generally useful to most users. See spread docs about the reliability guarantees to know when this message will be sent by the server.
  * handle\_timer() called once in a while by the AsyncSpread loop() method, used by SpreadPingListener to implement ping request timeouts.  (Interval is once per second, currently hard-coded)_

The SpreadListener also maintains group membership sets automatically, so you can always ask for the current group membership for any group that you have join()ed, using:
  * get\_group\_membership(group) - returns a set() of client private names that are current members of 'group'

Because the AsyncSpread class builds on asyncore.asynchat, it is not easy to mix threads with the code.  The interface to the Listener and the AsyncSpread class is not thread-safe, at this time.  If you do require threads, then devote a single thread to all AsyncSpread calls, or implement locking outside the library.  This will be cleaned up at some point to avoid these kinds of problems.

For single-threaded uses, the code is designed to let you dip into the asyncore main loop by calling AsyncSpread's loop() method with count and timeout parameters that permit you to put an upper bound on the length of time spent inside that loop.  There is also a one-shot poll() method on AsyncSpread that spends about 1/1000th of a second in the asyncore main loop.  It's important not to starve the asyncore main loop, to avoid the risk of poor application network responsiveness.  This is where Twisted and other event-handling frameworks probably do things a lot better.  Anyhow, this isn't Twisted, so I'm not creating a whole event processing framework in this code.  The new "