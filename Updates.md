# Latest News #

### December 31, 2010 ###

Happy new year!  My 2011 resolution is to get the code done with a beta release in January and a production release no later than February and a PYPI release at that time.

### December 4, 2010 ###

The project isn't dead!  I'm back from a vacation to Venice, Italy and will try to make the first 1.0 release before the end of this year.  It will be difficult, but I think it's doable.

### September 21, 2010 ###

I just made some updates to the example heartbeat server/client applications.  I finally took a few moments to implement something I've been dying to implement: a form of one to many RPC with a single responder.  It works like this:

  * Multiple listeners join a common server channel
  * A client sends a single request to the channel (without joining it)
  * Each server computes a hash based on:
  * The number of listeners
  * The position of itself within that list
  * The hash of the sender's name with the number of listening servers
  * The hash is taken modulus the number of servers
  * If the modulus of the hash is equal to the position within the list, then that server is the only responder

It's self balancing with a uniform distribution and ends up being really scalable.  The code is only 7 lines of python, using the crc32() method of the binascii module to compute the hash value.

It has some very nice RPC properties, as well.  When the list of servers (listeners) doesn't change, a single client will always get responses from the same server.  This enhances cache-locality.  Unfortunately, every time a server joins or leaves the group, the client to server mapping is scrambled, so cache-locality shouldn't be counted upon for scaling.  Another great property is that the servers don't have any dependencies on one another, so you can stand up more servers without incurring any additional load on the rest of the servers.  This provides true uniform scalability.  There is an additional cost within spread, but for now I want to assume that the cost of sending a message is insignificant compared to the cost of performing some kind of work for the request.  Another nice property is that when a server leaves and rejoins the group, the original client to server assignments are restored to their previous state.  This means you can bounce a server, and as long as the server is down for only a small time, you don't incur a large cost for breaking cache-locality.  Another advantage is that it is completely decentralized.  Because spread is decentralized, and this distribution algorithm is decentralized, it means there is no single point of failure anywhere in the system.  Very satisfying.


### September 20, 2010 ###

I've uploaded a new version, 0.1.4a to the Downloads page.  This version contains a few minor fixes and adds a little more functionality to the GroupCallbackListener.  The changes are what I describe in the Sept 19 update (below).

I decided to disable the AsyncSpreadThreaded subclass in this version, and instead of trying to release a dual API via subclassing that is thread safe and reentrant, I want to focus on just getting the asynchronous nonblocking (but single threaded) version out the door.  The threaded version is just too messy at the moment.  I don't feel comfortable in anyone using the threaded version in production.  It raises a ` NotImplemented ` exception if you try to use it, for safety.

I'm also working on sample code, in the SVN repo under trunk/test/example\_blah.py which currently contains a single Heartbeat server and client implementation.  The code idea is that a Heartbeat group (channel) exists as ":HB" and the HB server instances listen on that channel.  Then, clients may send a message to that channel, without even joining it.  The HB servers then individually send a unicast acknowledgement response back to the client, including their current count of how many heartbeats they've received.

I was going to use the GroupCallbackListener for both server and client, and realized very quickly that the code I copied from the client would be far smaller and simpler if I implemented it as a SpreadListener subclass.  So, that's what I chose: the HB client is a GroupCalbackListener and the server is a subclassed SpreadListener.

I found one bit of annoyance when subclassing the SpreadListener class.  I had to explicitly call the superclass ` __init__ ` constructor in my subclass, or else I got a very cryptic exception when I received the first message on the wire.  The SpreadListener class sets up a couple instance variables in its ` __init__ ` method, which weren't happening in the subclass, so other methods bombed out.  I am thinking now that I might want to do that setup lazily perhaps.  It is a bit ugly, but I could have a ` ._setup() ` method that the AsyncSpread class invokes on startup... It could do the work once, and be idempotent at it.  But it feels like a hack to me.  On the other hand, I could have a well defined ` setup() ` method that is always invoked by the constructor, and tell users not to have a constructor, but to do it in the ` setup() ` method instead.  But that seems like I would be reinventing the inheritance model, and poorly at that.  It's a minor nuisance at the moment, but it's something I want to change.  The server code should look a tiny bit simpler, I think.

One thing that is kind of cool is that the HB servers are aware of each other, due to the ` handle_group_join() ` and ` handle_group_leave() ` callbacks invoked by membership to the :HB channel.  I could easily add some logic that would use hashing on the group membership list to compute a single "responder" to a multicast client message, which would let the system scale really well.  Adding additional servers would decrease the workload linearly.  Maybe soon I'll add something like that to the sample code.  If I can make the code very small, it seems like a cool demonstration of new ways of doing RPC on a message bus.

The reconnect code is still a bit tricky, and I'm starting to think it's okay to require users to wrap the ` .multicast(), .unicast() and .join() ` calls with try/except, mostly because it adds a layer of protection to client code.  I'm pretty sure the error handling is robust in the library, but it's a lot of code to consider.

Anyhow, this is another release that brings the code one more step to the next release which will be 0.2a and happen in the next couple of weeks.




### September 19, 2010 ###

I'm back on the code now, after a long international trip in August.  In the last day, I rounded out the GroupCallbackListener a bit, by adding a callback for receiving a message for a group that has no callback handler.  That should be an interesting use case for someone, I think.  I also added a method to the base AsyncSpread class to return the client's private map dict() variable.  This will make it easier to share a single map() instance among multiple clients, without having to explicitly create the dict() in client side code.

I'm starting on sample code in the test/ directory, including example\_listener.py which I will probably rename to something like example\_groupcallback.py to be more clear.  I'm using my code as a user now, so it's interesting to see the challenges I've made for people with this API design.  One thing that I think is really annoying is the exception throwing when a connection is down and you want to send a multicast or unicast message to it.  It's somewhat obnoxious to have to wrap every message send and join with a try/except, so I'm thinking of how I can make it easier for users without making the API so flexible that it is overwhelmingly confusing.

For now, I'm going to ignore the threaded version of the class and focus on nailing down the non-threaded version.  It's disappointing that I've gotten so far but still have some fundamental design problems in dealing with reentrance and thread safety.  I want to get to an actual release first with the non-threaded API.  It's still asynchronous and non-blocking, so it works fine for anyone who needs that kind of API.  I should make a client-threaded example that does all the threaded interaction via 2 Queues and a worker thread that sits on run().  Then it's clear how to use the code in a threaded context safely.

I have a few to-do items before I can get to the next version release.  I have to:
  * rewrite the SpreadException code, it's non-pythonic
  * add unit tests with no external (spread daemon) dependencies
  * write docstrings for everything, and generate epydoc for the API
  * write example programs for:
    * Heartbeat channel
    * Log channel with consumers
    * Ping test channel
    * shared dbus channel? one way or two way?
    * Distributed worker channel: worker computed from membership list (failover?)
    * Plugging in a serializer for payload (protocol buffers?)

So, there's still a lot of work ahead.




### July 17, 2010 ###

After a bout of food poisoning and a minor earthquake in Washington, DC, and a long work-week, I'm back on the code.  I took some time to look at all the junky print statements that were cluttering up the code, and went through and did a big cleanup to replace all the junk I want to keep with calls to the standard logging module's debug/info/warning/critical() methods.  I still have many print statements left, but they only will live while I continue to debug and restructure the code while I make the threaded version work.

In fixing up the logging, I also put in try/except handling around _all_ the user callbacks and included a logged error message with the exception at critical() level, and a full traceback logged to info() level.  This should help _immensely_ in troubleshooting user applications.  I was stymied myself several times, wondering where my test code had exploded, and got frustrated enough to comb through the code and pick out every callback invocation and every try/except to instrument the except clause with this traceback logging code.  Ahh, how nice to see actual line numbers and lines of code where the real problem happened...  So much better, and elegant to have it sit on top of standard logging.

Another change I made was to stick thread safety into the SpreadPingListener class.  I only realized today that threaded users of the ping listener would potentially have multiple threads entering the ping() method, which would be terribly confusing if two threads got the same ping ID.  It wouldn't be pretty.  So, a single threading.Lock() object and about 20 lines of code later, I think the SpreadPingListener class is now thread-safe.  At least, if it has any problems, I don't think it will explode now.

Making the threaded version work has revealed a lot of issues that I'm working on.  I've come to understand that the  public facing methods need to do less work individually, and delegate some work to helper methods for doing the IO or waiting for the IO thread to do some work.

The run() method was on the chopping block, but then I realized that the GroupCallbackListener class's method join\_with\_wait() needed to either dip into the non-threaded class's wrapper to asyncore.loop, or just implement a sleep() for the threaded version.  This mapped directly into an internal _do\_poll() method which puts the two different behaviors in each class.  The run() method is now completely public-facing, and is safe to invoke from user-code (but not in a user callback)._

The two situations which are both deadly are call-stack related:
  * Scenario One:  a non-threaded user handler invokes the main run() method, which then does more asyncore.loop() which then invokes the handler again, and it continues until a recusion overflow exception is thrown.  And thrown.  And thrown.
  * Scenario Two: a users' 'dropped connection' handler is invoked in a threaded context by the IO Thread, and the user code (running inside the IO thread) does something stupid, like sleep() or worse, wait\_for\_connection() which blocks on an Event() object, that is never set() because the IO Thread is doing nothing now.

Both scenarios are situations where the public-facing API has to work when it's invoked from two different contexts: in non-threaded code it is between main application code versus handler-code callbacks, and in threaded code it is between user-thread execution and handler callback execution within the IO thread.

I found that I could easily detect whether a public-facing method was being invoked by a handler callback in the threaded version by testing threading.currentThread() to see if it is the same object as self.io\_thread (saved when the IO thread is made at constructor time.)  This was payoff from choosing to always instantiate the IO thread in the threaded constructor, because now I can count on self.io\_thread being available to test against.

It looks like I need to implement nearly identical testing in both non-threaded and threaded versions, to check the calling context within the public-facing methods, and avoid dipping back into the IO loop or doing unsafe blocking operations when the caller is executing within a callback handler (i.e. when it is a recursive call, or a call from within the IO thread itself).

I'm a little worried that this is going to make the code really ugly.  I'm trying not to get too fancy with it, so the obvious solution is to code an _is\_callback\_context() method that both versions implement, with different tests, for the public-facing methods to use to test before doing unsafe operations.  One would test thread object identity and the other would check a flag that is set and unset on entering/leaving the handler (or on entering/leaving asyncore.loop() even)._

I've learned one thing in this process: writing a client library that works as a non-threaded AND threaded implementation is challenging.  I'm finding that I have to make a stronger separation between user-facing calls and internal calls.  I don't see any "magic bullet" that will make this easier, other than to lean heavily on overridden methods that each version implements differently, and ensure I have factored out all those behaviors so the overlying logic is still clean.

At least this _is\_context\_callback() method (acting kind of like a context manager) is generalizable and covers both cases.  It reflects the truth that this API is not fully reentrant._

. . .

Later that same day...

I just read through some of the Twisted tickets/issues tracker and found exactly this same issue that was reported 4 years ago and resolved 4 months ago.  Not coincidentally, their method is named run().  Their approach is to raise an exception if a callback attempts to reenter the main loop, by checking a self._started boolean.  Interestingly, they also have a self._stopped variable, so I am guessing they also have interstitial states between started and stopped, as I do with the interstitial states between issuing a start\_connect() and actually being connected.




### July 14, 2010 ###

I sketched out the pieces and decided to remove the auto-reconnect feature for now, until I can get the threaded implementation fully sorted out.  Reconnect is still an option, but it will have to be triggered by user code, not by the client itself.  That's probably for the best, anyways.  It's also almost trivial, so it's not a huge imposition.  Plus most clients will likely want to do something slightly unique in order to reconnect (special penalty logic, failover, etc).

I think the io\_ready threading.Event object should be renamed to 'session\_up', and I need a new 'session.shutdown' Event object to prevent a thread-safety problem in the disconnect() method.  Looking at the truth table of session\_up and session\_shutdown, the various combinations make perfect sense and map to specific states or state transitions for the actual connection.  Seeing no invalid states gives me more confidence that these primitives are a good fit to what I need.

. . .

This strategy is paying off.  I've been able to remove the io\_ready member, and replace it entirely with session\_up (both as a threading.Event object.  Instead of testing against the value of session\_name (being non-None), I've switched more tests against session\_up.isSet() which is clearer.  And... just finished changing **all** the tests to use the threading.Event isSet() check on self.session\_up, so the test is thread friendly everywhere.  I should probably make this an internal method, _is\_up() or something to reduce the duplication._

Another change I'm going to make now is to start up the IO thread in the AsyncSpreadThreaded constructor, and just eliminate the possibility that the IO thread has not yet been started when the rest of the code executes.  I still have to have an exit condition, which needs to be separate from the disconnect() method's session\_shutdown (that I haven't yet put in).  Anyhow, the thread startup logic (locking and rechecking later) is superfluous.

. . .

Now I'm changing the self.do\_restart to **also** be a threading.Event() so the IO thread doesn't have to sit in a fairly tight polling loop to get connected promptly.

There is finally light at the end of this tunnel.

### July 13, 2010 ###

I'm attacking the event loop API now, to make the threaded and non-threaded usage more similar.  This looks a little easier than refactoring the connection-state flag variables, and is probably a prerequisite to getting it cleaned up anyhow.

Changes:
  * renamed loop() to run() but borrowed the asyncore.loop() parameter names: timeout and count.  When count is not specified (set to ` None ` by default), then run() becomes an infinite loop.
  * killed io\_active, which also eliminated the check that run() would be called in the threaded version... which isn't a problem after all because run() is reimplemented in the threaded class.
  * removed threaded version of poll(), now threaded class uses the inherited poll() method


### July 12, 2010 ###

I'm doing more file reorganization tonight.  asyncspread.py is now connection.py, and I'm rejiggering the test/ scripts so they use the new names.  I'll probably miss a couple spots here or there.  We shall see.

### July 11, 2010 ###

Still have lots of refactoring to do on the IO event loop and on the connection state tracking, but I took a side trip down the package-building rabbit-hole and made my first ` setup.py ` script.  Again, I'm amazed at python's simplicity.  With just 8 lines of code, and technically just one import and one method call, I have a functional setup script.  I used it to build both a tarball of the code, as well as an RPM!  I wouldn't install the RPM on a production system, there's just way too much changing at the moment.  But I took the liberty of uploading the first preview release (**very** alpha!) of the asyncspread code as asyncspread-0.1.0.tar.gz in the Downloads tab of this google code project.

Here is what it contains:
```
 # tar tvfz dist/asyncspread-0.1.0.tar.gz 
 drwxrwxr-x willp/willp       0 2010-07-11 09:36 asyncspread-0.1.0/
 -rwxrwxr-x willp/willp     321 2010-07-11 09:36 asyncspread-0.1.0/setup.py
 drwxrwxr-x willp/willp       0 2010-07-11 09:36 asyncspread-0.1.0/asyncspread/
 -rw-rw-r-- willp/willp    5477 2010-07-11 09:31 asyncspread-0.1.0/asyncspread/message.py
 -rw-rw-r-- willp/willp    3282 2010-07-11 09:31 asyncspread-0.1.0/asyncspread/services.py
 -rwxrwxr-x willp/willp   40812 2010-07-11 09:31 asyncspread-0.1.0/asyncspread/asyncspread.py
 -rw-rw-r-- willp/willp      51 2010-07-11 09:31 asyncspread-0.1.0/asyncspread/__init__.py
 -rw-rw-r-- willp/willp     257 2010-07-11 09:36 asyncspread-0.1.0/PKG-INFO
```

I'm embarrassed to realize now that the main filename probably shouldn't be the same as the package name.  It's a bit weird to import asyncspread.asyncspread to get the main AsyncSpread class imported...  So I'm likely going to change the main filename to something like connection.py and perhaps even split out the listener code into a listener.py file, and the exceptions.

This file reorganization is overdue.  And, for too long I have needed to learn how to build distributable python packages.  It's pretty hard to contribute to the python community without building proper packages.  I've got my PyPI account set up now, and once I get a little further down the packaging and file organization road, I expect to release this as a 1.0 release that will have a pretty stable API and lots of documentation.

For now, though, 0.1.0 is the current "release" version, so feel free to download the tarball and experiment.  Note: the test scripts are NOT included, so you will have to check those out using the SVN browser or an SVN client.

I'm still amazed at how simple it is to build an RPM using distutils (setup.py).  I have to learn a lot more still, including how to specify arbitrary options to rpmbuild, like setting the options for rpmbuild version 5 to tell it to build an rpm 4 compatible RPM:
```
# this tells RPM v5 to build an RPM that RPM v4 will work with:
%define _binary_payload w9.bzdio
%global _binary_filedigest_algorithm 1
%global _source_filedigest_algorithm 1
```

Somehow that's got to get passed into the specfile for rpmbuild by way of the ` bdist_rpm ` subcommand to setup.py.  Ah, well, I'll figure that out later.  Maybe if I look at how things like python-dns or python-simplejson are packaged up by the Fedora/redhat crew, that will help.



## July 10, 2010 ##

It's been a while since I've updated this page, so here it is.  I am struggling with the conversion of the code to the threaded model.  I'm just not excited about the guts of the internal scheduler.  It's really gross and must change.  The subclass for threaded usage is a bit painful.  It works, but it's clumsy.  I've been trying to spy on other open source projects' methods, and it seems that there aren't very many APIs which implement both single-threaded and (real) multi-threaded usage models.  If you know of any, please let me know.  I would prefer to borrow someone else's wheel than reinvent one myself.

Other aspects of the code are shaping up, too.  I broke the code out of one big file, into 3 separate files.  The message classes all end up in message.py, and the service code in service.py, with the main class staying in asyncspread.py.  I'm hopeful that this will make it a little cleaner to roll up into a single package (with a init.py file specifying the three files in all).  I've only messed around with that way of packaging python code, so I'll have to bone up on the details and start to work out the details of setuptools/dist/pip/etc.  Packaging up for PyPI is a big goal.

Notes from today's hacking on the code:
  * rename self.private\_name to self.session\_name
  * eliminated session\_up, convert all tests to: ` self.session_name is not None `

Identified need to clean up:
  * ` self.shutdown, self.dead, self.session_name, self.connected, self.io_ready, self.io_active, and self.do_reconnect ` - there should be fewer and less confusingly named values, with proper leading underscore on whatever survives.
  * Also must clean up/unify: ` self.poll() and self.loop(), self.do_io(), self.start_connect(), self.wait_for_connection(), self._do_connect() `


Object member variables and their usage:

self.dead:
  * starts False
  * set to True in asyncore over-ridden ` self.handle_close() `
  * set to True in: ` self._drop() `
  * cleared (set to False) in ` self._do_connect() ` immediately before ` self.connect() `
  * Checked in ` self.wait_for_connection() ` - causes return False, breaking out of loop
  * Checked in ` self.poll() ` - causes ` poll() ` to return False immediately
  * Checked in ` self.loop() ` - causes ` loop() ` to return, breaking out or skipping loop
  * Checked in threaded ` self.do_io() ` - causes asyncore looping to skip, but doesn't stop method from looping

self.shutdown:
  * starts False
  * set to True in ` self.disconnect() `
  * Checked in threaded ` self.do_io() ` - causes IO thread loop to exit and thread to terminate
  * Checked twice in threaded ` self.do_io() ` - checked to stop pulling messages off out\_queue in loop that sends them via ` self/asynchat.push() `

self.io\_active:
  * starts False
  * Checked in ` self.loop() ` - raises IOError() exception if it is set True, to avoid mix of threaded and non-threaded usage
that's it... this looks like i need to kill it.

self.io\_ready: (Threading.Event)
  * starts in AsyncSpread contructor as threading.Event()
  * Cleared with ` io_ready.clear() ` in ` self._drop() `
  * Set with ` io_ready.set() ` in self.st\_set\_session() after ` self.session_name ` is set
  * Cleared in threaded ` self.start_io_thread() ` while ` self.io_thread_lock ` is held locked.
  * Waited on in threaded ` self.wait_for_connection() ` with ` io_ready.wait(timeout) `

self.connected: (from socket)
  * not checked except to force it to False in ` self._drop() ` if it is set to True, only happens in python 2.4, not in python 2.6+

I clearly need to do some refactoring here.  I probably need to separate the admin from the operational state of the connection.  Also, the API for dealing with connection-state is pretty gross.  Then there's the two completely different event loops and lots of cut n paste between ` poll(), loop(), and do_io() `.  That's not smart.

It's nice to go away from the code for a while and return to it with fresh eyes and a fresh mind.  Now on to fixing the messiness... I think one criteria of a good design here is that the API should be nearly identical between threaded/nonthreaded use, and there should be minimal duplication of code.  Also, there shouldn't be any ambiguity about the 'state' of the connection.

**API Fixes**

Added a start\_connect=(True|False) option to the ` AsyncSpread and AsyncSpreadThreaded ` constructors, to simplify usage and avoid extra work in client applications.  I purposefully avoided permitting the threaded class from having the superclass invoke the start\_connect() method, to ensure the call ordering is absolutely clear.  It's a bit hackish, but so is having a constructor that also performs a connect() operation somewhat abstractly.  So, I'm fine with the 3 extra lines of code that ensure the superclass doesn't try to start\_connect().



### June 5, 2010 ###

I put some effort into cleaning up the threading model.  It's a lot more complicated than I like, at the moment.  Subclassing AsyncSpread as AsyncSpreadThreaded has resulted in a really overly complicated object model.  I can barely understand the execution path, when the subclass jumps between over-ridden methods and parent methods.  This is a clear sign that I haven't really figured out the inheritance model for a threaded subclass.  The ultimate goal is to have a very intuituve class model, where you can drop in a threaded AsyncSpread object in place of a non-threaded object, and painlessly get almost identical functionality. I'm a bit far from that.

In good news, I actually figured out a way to make the base asynchat class work with a private 'map' parameter in both python 2.4 and 2.5+!  It's only a few lines of code, but IMHO it elegantly corrects for a missing 'map' parameter to the asynchat class, without sacrificing _anything_ whatsoever, plus it works in 2.4, 2.5, 2.6 etc...  This makes threaded python 2.4 asynchat/asyncore applications practical and non-lethal. :-)  I'm actually pretty excited about this snippet of code.  I may submit it to Alex Martelli to see if he wants to include it in the Python Cookbook, assuming a new edition is in the works at some point.

For now, I'm working on the threaded class, AsyncSpreadThreaded.  It needs a LOT of work.  I don't like the while TEST: sleep() loops that exist in a few places, so I want to replace those with true threading.Lock wait() calls instead.  I'm making progress, extracting out (2 so far) locks for very specific conditions that make a lot of sense.  So, I'm hopeful I will get closer to a usable and **solid** threaded client.


### May 16, 2010 ###

I spent some time working with the new IO thread functionality, and though it actually works, it isn't exactly how I want to see it.  I thought a bit and realized that I need to make explicit the threaded usage, instead of relying on 'hints' from internal flags... This might even be time to subclass the AsyncSpread class (for the first time) to stick on the threading functionality, and properly override the methods that need thread-safety changes, so at instantiation-time a user selects the behavior they want, rather than by making runtime calls to do this or that (i.e. start up the IO thread).  It should be extremely explicit here, in what is happening.  That will clean up a lot of the ugliness that showed up with the threading support.  Ideally, asyncore and asynchat need to be thread-safe.  Perhaps in another life I'll take that task on.  Ah well.



### May 15, 2010 ###

I've added in the TCP keepalive support, which was pretty straightforward.  I looked at the packets with tcpdump -vv and it's really clear that the kernel is doing the right thing.  The default behavior is to enable TCP keepalive, and the timers are set to deliver a keepalive packet once every 10 seconds, and to consider the connection as broken when 6 keepalive packets are not acknowledged by the far end, so it's a 1-minute timeout.  This puts an upper bound on the maximum time that a connection can be black-holed by a misbehaving NAT or firewall.  Keep alives are really lightweight and are implemented at the OS level, so this feature will cause no increase in CPU to the server or the client application processes.  The bandwidth is minimal (52 bytes in each direction, once every 10 seconds is ~42 bits/sec and 0.1 packets/second, very cheap!).

Here is a packet trace showing the TCP keepalive packets over a 30 second period of time between my client running on IP 10.0.1.184, talking to a server at "x.y.z".net:24999:
```
15:35:32.644512 IP (tos 0x0, ttl 64, id 30653, offset 0, flags [DF], proto TCP (6), length 52)
    10.0.1.184.57700 > x.y.z.net.24999: Flags [.], cksum 0xed1d (correct), seq 2183, ack 1032, win 92, options [nop,nop,TS val 108396278 ecr 1737950730], length 0
15:35:32.737345 IP (tos 0x20, ttl 47, id 52421, offset 0, flags [DF], proto TCP (6), length 52)
    x.y.z.net.24999 > 10.0.1.184.57700: Flags [.], cksum 0xecf2 (correct), seq 1032, ack 2184, win 175, options [nop,nop,TS val 1737960819 ecr 108386148], length 0

15:35:42.736511 IP (tos 0x0, ttl 64, id 30654, offset 0, flags [DF], proto TCP (6), length 52)
    10.0.1.184.57700 > x.y.z.net.24999: Flags [.], cksum 0x9e48 (correct), seq 2183, ack 1032, win 92, options [nop,nop,TS val 108406370 ecr 1737960819], length 0
15:35:42.824810 IP (tos 0x20, ttl 47, id 52422, offset 0, flags [DF], proto TCP (6), length 52)
    x.y.z.net.24999 > 10.0.1.184.57700: Flags [.], cksum 0xc585 (correct), seq 1032, ack 2184, win 175, options [nop,nop,TS val 1737970912 ecr 108386148], length 0

15:35:52.824642 IP (tos 0x0, ttl 64, id 30655, offset 0, flags [DF], proto TCP (6), length 52)
    10.0.1.184.57700 > x.y.z.net.24999: Flags [.], cksum 0x4f73 (correct), seq 2183, ack 1032, win 92, options [nop,nop,TS val 108416458 ecr 1737970912], length 0
15:35:52.909005 IP (tos 0x20, ttl 47, id 52423, offset 0, flags [DF], proto TCP (6), length 52)
    x.y.z.net.24999 > 10.0.1.184.57700: Flags [.], cksum 0x9e1f (correct), seq 1032, ack 2184, win 175, options [nop,nop,TS val 1737980998 ecr 108386148], length 0

```

I'm going to finish up the CallbackListener class and also completely rejigger the way the 'SEND\_PKT' is built, with the new call to set the reliability level of messages.  The SpreadProto class will grow from this work.

Ok, I've finished the CallbackListener, which looks pretty clean, amazingly.  One thing that's a little weird is the possible expansion of a message that was sent to multiple groups into multiple group data callbacks.  I like it, but it sure could be hard to troubleshoot if you're not expecting a single message to trigger multiple callbacks.

Now I'm working on making the code thread safe.  This may be more effort than it is worth for the first pass.  But I'm giving it a shot anyways.  The code currently explodes pretty quickly when two threads both enter the asyncore.loop() method, raising a `<socket._socketobject object at 0xb745e95c> Exception: deque index out of range` error.  This isn't surprising because asyncore itself is not thread-safe.  I'm adding a deque() that will be used instead of the self.push() calls in the public facing methods of join(), leave(), multicast() and disconnect().  There may be some really tricky edge cases, especially when the connection is dropped... I want to make it super-easy to use and support both threaded _and_ non-threaded uses.

Wow, adding thread-safety took 5 minutes.  A single collections.deque() object, a boolean flag, and a helper method (_send()) to invoke instead of push() that knows how to send the data, and a do\_io() method is all it took.  Amazing.  I'm surprised._

### May 8, 2010 ###

This update is exciting.  I'm getting so much closer to being able to release this code, I can nearly taste it.  Bit by bit, I'm resolving the problems and adding more functionality.  It's getting exciting now.  This is going to become my first PYPI release, so I'm aiming to make this as good as I can.

In the latest big commit, I fixed all of the group handler_methods so they include the connection object, which makes the handler\_() methods more uniform.

Added a new handler for handle\_network\_split() which is invoked whenever a NetworkMessage is received, regardless of it being a split or an unsplit.  The args passed to the handler are pretty helpful, I think: the size of the change (positive or negative delta), the old membership set(), and the new membership set().  This handler is invoked _before_ the individual handle\_group\_leave() or handle\_group\_join() calls.  This should be quite useful for any client that needs to do special work on a network split.

I also pulled out all the debug statements and made a new listener class: DebugSpreadListener, which you can use with multiple inheritance to add debug output to some other listener.  It may not be viable, but it works better than I expected.

I realized that not everyone really wants to code up a new class just to deal with a spread connection, so I'm working on a CallbackListener which wouldn't be subclassed at all.  Instead, a user would instantiate a CallbackListener, give it some callbacks for various events, and register more callbacks for messages.  This CallbackListener might even be useful as a subclass to other Listener classes that do various forms of message routing to code based on different criteria, like group->callback, or mesg\_type->callback, or combinations: group+mesg\_type -> callback.  This is where it gets terribly interesting.

Another enhancement that I realized I need to make is to add the magic of TCP KEEPALIVE to the asynchat socket, as an optional (enabled) action in the AsyncSpread class.  This will ensure that a connection to spread _will_ be terminated if the network becomes a black hole.  This is gravy, but valuable gravy.  It's pretty easy to add, and puts zero extra load on the remote spread process.  The only load it adds is low rates of network traffic that are handled purely by the operating systems of either side of the connection.  The client process and daemon process aren't involved.

I've also tested the spread client over a high latency connection to the spread daemon, and it works nicely.  I'll run some more long-duration tests to see if it stays up for days.

### May 5, 2010 ###

There's a lot to report this time.  The listener class(es) are working great, and the core protocol code is getting even tighter, plus I added a major bugfix and API change with join/leave, that only can handle one group at a time.  Here's the svn commit log which has more details:

big fix- join and leave only REALLY work for a single group at a time, i had to look in the server source (session.c) to see that the daemon really only looks at the first group given in a join or leave message.  that bug lingered for a long time. wow.

also, finished removing the ping timeout functionality and have a periodic call into the listener's _process\_timer() method where the SpreadPingListener performs ping timeouts_

added ping send/recv packet counters, so you can get "packet loss" stats.

i also realized that the "SEND" packet value was really the RELIABLE\_MESS value, so I have a new (small) can of worms to fix- how to best handle changing the service\_type (the reliability class) among: UNRELIABLE, RELIABLE, FIFO, CAUSAL, AGREED, SAFE... It needs to remain efficient, but also be simple and easy to modify.  I am leaning towards a .set\_default\_service(SpreadProto.RELIABLE\_MESS) method, which calculates the packed int for that level, and for the "noreflect" version.

I'm also thinking that I need to add more debug statements to help application developers troubleshoot at the application level. this is still an idea in progress though.

I also hope to try out some multiple inheritance to mix together a ping listener with a debug listener... or provide some mechanism for easily adding debug behavior to any listener.

through continued refactoring, i was able to completely remove the st\_read\_memb\_change() state, since it was identical, line for line, with the read message body method, now that membership changes are calculated entirely in the listener.

i also converted almost ALL debug output to logging module logger.debug() calls and added a nullhandler log object (as recommended by the logging module docs).

wired up the asyncore handle\_error() method, so that it now calls the users (listener's) handle\_error() method, passing the exception object in the same way the SpreadException object is sent!  This looks super clean now.  It even clears the exceptions there too. Neat. I expect I'll need to add a traceback object of some sort down the road...  Ehhh, later.

Added docs to constructor for AsyncSpread. Removed useless instance variables (group membership dict, start\_time). Started to clean up the tra/ts test scripts.

and from the previous commit:

removed cb\_dropped and cb\_connect callbacks, instead am calling the listener's _process_\_methods, which then invoke local handle**\** methods_

also, added new handle\_error (and _process\_error) which replaces the ill suited raise SpreadException() calls that were sprinkled throughout the handshake and connection processing code.  this is starting to look really clean now._

made first stab at properly doing logging using the logging module... this may be tricky for a little while, to make sure the library plays well as a library.

also i realized the SpreadException class desparately needs to be subclassed into categories, with perhaps an errcode -> exception class lookup map to make it easier to map spread errno to exception classes.  i think maybe 3 classes overall will be needed, connection level errors, protocol version/authentication errors, and others.  we'll see, it's not a high priority though.

the pinglistener code is still messy, and i've made no progress on filterchain style (MINA inspired) processing.  plus, the ping expiration part is just disabled for now, so i have to figure out a way to hook onto or implement a timer resource/callback from the poll/loop back to the listener, so it can spend time doing work if needed.

thread safety is another concern that weighs heavily.  i'll get there.



### April 25, 2010 ###

Finally finished migrating the message processing to the new Factory approach.  The new code is so much cleaner, it's a relief.  The SpreadListener base class is finally usable, but I still have the "self-ping" functionality buried in the AsyncSpread class, which has to change.  I'm thrilled that some long-duration testing has proved the reliability of this code.  Various versions of the code have been running non-stop for weeks, without any failures or unhandled exceptions.  The TCP connection to the Spread daemon is super reliable.  No issues there.

I like seeing the debug output that shows off the new Message classes, like DataMessage.  Check it out:

```
!-!-!  SpreadListener:  Received message: <class 'asyncspread.DataMessage'>:  sender:#tra-000054#dev103,  mesg_type:65535,  groups:['#tra-000054#dev103'],  self-disc:False,  data:"PING:92644:1272210857.79026604"
GOT MESSAGE (mtype:0xffff) 93769 (30 bytes):  PING:92644:1272210857.79026604
Client PING callback: Success= True
   Elapsed time: 0.00193095
```

I'm slowly removing lots of debug output, but haven't yet switched the code over to using the logging module.  A higher priority is to fix up the main loop to be less stupid, and easier to work with for both non-threaded and threaded environments.

...

I'm now working on a new SpreadPingListener, which has me scratching my head because now the ping() method belongs in the SpreadPingListener class... It's definitely weird to have the ping() implemented in a Listener class... Listeners shouldn't speak... I'm going to finish moving the ping() code out of the main AsyncSpread class, and then take a second look at where it best belongs.  The code is sprouting new classes all over the place, so I'm nervous about adding any more classes that only serve to be 'pure'.  Instead, I might look for a different adjective than "Listener" and call it something else, like Processor or Manager...  I'm thinking a lot.

### April 8, 2010 ###

Got the message factory ironed out.  I'm still removing the old style message creation, though.  And I'm starting to move the callback mechanism out of the Asyncspread class, and into a SpreadListener class.  This will make it super easy to implement different message-dispatch mechanisms by subclassing SpreadListener, or by implementing its protocol ("Interface" to java folks).

I didn't really expect to go in this direction when I started, but it makes a lot of sense now that I've actually implemented a group registration process for callbacks into user code.  The asyncore/asynchat derived class gets so messy dealing with the message-routing specific logic, it ends up looking like spaghetti.  So I'm repeatedly refactoring.  One nice part of this refactoring is that the code is simplified, and easier to enhance.  After I discovered the "SELF\_DISCARD" flag and tested it out, it was a piece of cake to add to the newly refactored DataMessage class without cluttering up any of the MembershipMessage classes.

Another cool thing, is that I learned you don't have to define a constructor for every class in python.  I don't know why, but I assumed they were necessary.  Well, not so, and now the various flavors of MembershipMessage subclasses have almost no code in them at all, except where it makes sense- like the extra boolean "self\_leave" property of LeaveMessage objects, which only makes sense for that specific message.

I'm still wondering just where I might stick a deque in all this, to make it easier to run multi-threaded code.  Maybe in the SpreadListener?  I'm also wondering what the listener's API should be.  And wondering if the various Message classes should be consumable by the code, or if they should remain purely output objects.  At the moment, sending a message or performing a join/leave/disconnect operation is just a method call, not an object creation (other than strings).


### April 7, 2010 ###

I'm again refactoring the code, to really clean up the message class.  The 'canonical' Java API for Spread has an extremely weak SpreadMessage class, and I realized that I was starting to mimic it for no good reason.  It is weak because a SpreadMessage object doesn't actually map to the _type_ of Spread message that it represents.  It is an unholy mess of boolean methods that you must query to determine what actual type of message you're dealing with.  And it also supports lots of methods that don't make any sense for a SpreadMessage of certain types.  For example, the getMembershipInfo() method exists for all SpreadMessage objects, but it is only valid when isMembership() returns True.  Otherwise, the result is undefined.

It looks like what's needed here is a tiny bit of class inheritance.  And I usually shy away from introducing layers of inheritance out of abject worship of simplicity, but here it just makes perfect sense.  There really are types of messages:  SpreadMessage -> (DataMessage, MembershipMessage, TransitionalMessage)  and MembershipMessage -> (JoinMessage, LeaveMessage, NetworkMessage).  It's not a deep hierarchy, and the basemost class will be pretty tiny.  I'm adding a MessageFactory class to deal with the appropriate creation of these objects from parsed spread messages (packets), which also seems to be a common use-case for a message factory pattern.  I am keeping a close eye on the efficiency, so that DataMessage objects are inexpensive.  This is where I think using python slots may help.

Once I get the MessageFactory ironed out and the individual classes wired up for the various message types, then I intend on refactoring the dispatch code that currently lives inside AsyncSpread's st\_read\_message() and st\_read\_groups() methods.  It's ridiculously overly complicated right now, so what I need to do is pull it apart a little bit, and let the code separate out into more uniform pieces.  Specifically, the AsyncSpread class will allow you to register a listener callback for various Spread message types, (DataMessage and MembershipMessage being the two big ones).  Those callbacks will then be able to deal with different message types without having to go through the rigamarole of testing isMembership(), isRegular(), causedByJoin(), causedByNetwork(), etc.  Instead, the methods can immediately implement the exact code needed to deal with that specific type of message.

Only at _this_ point is where it makes any sense to process callbacks for data messages, versus callbacks for membership-change messages.  It's not really rocket science, just moving some deeply nested and redundant code out of the st\_read\_message() and st\_read\_groups() methods that currently live in AsyncSpread.  This opens up a much cleaner API for implementing different types of message dispatch strategies.  For example, one client may need to map a received message to a specific handler based entirely on the group it was sent on.  Other clients may need to include the 16-bit message-type header value as part of the message call dispatching, to route a message to an application-specific handler method.  Yet another client might not care at all about which groups a message was sent to, or what the message-type is set to, so a single data message handler is all that is required.  Or suppose a client only needs to care about membership messages, and needs to discard all DataMessages.  This is where it makes a lot of sense to me, at least, to break apart the message->code routing into another layer.  I suspect I'll end up implementing a few different MessageDispatcher classes that implement convenient APIs for each of the use-cases I just described.

So, that's what's going on now.  I probably typed more characters describing the changes than the code will sum up to.  To sum up, for poor grammar's sake, a preposition is what I will end with.


## Recent News ##

### March 31, 2010 ###

I've made a lot of progress on the packet marshalling code, and I'm done converting the code to being completely non-blocking.  I'm pretty sure this code won't ever get out of sync with the server, now that it understands the header fields _much_ better.

The API only exists as scribbles on a notepad, but I'm thinking it will support two modes of operation:
  * Single-threaded: clients explicitly call a loop() method with a timeout parameter similar to asyncore.loop()
  * Multi-threaded: a single background thread dealing with the IO by wrapping asyncore.loop() with a thread, and messages are enqueued and dequeued from two thread safe deque objects by the client.  I'm not 100% sure on the details yet.

Note: I use the words "channel" and "group" interchangably.  When I write "channel" you can understand it to mean "Spread group", with no special meaning attached.  I personally think in terms of "channels" more than "groups".  Sorry for any confusion.

## Thoughts about the API ##

So far, the API looks pretty simple.  join(), leave(), disconnect(), multicast(), unicast(), and now ping(). The next big thing to add are either callback listeners, or queue based "listeners" (multi-thread safe).

This is where is gets tricky.  If the API and data-paths are too complicated, then simple use-cases will require a lot of plumbing, which would suck.  But I don't want to make too many assumptions about the behavior of the end-users of this API.  Of course, there are no end-users yet, just me, so I am trying not to impose my own particular needs on everyone else.

## The protocol ##

The protocol is both interesting and annoying.  It's interesting that every data message a client receives includes the list of groups that it was sent to, even if the client is not join'd onto those groups.  So there's a hidden "cost" when multicasting a message to multiple groups, if your group list is long, and clients only subscribe to a small subset of those groups.  The exact cost is 32 bytes per group, in the message header.  You could consider this to be a kind of "information" leakage, where a client can tell what extra groups a message was sent to.

At first, I didn't like this feature of spread.  But, actually- it opens up some really interesting functionality.  I can think of several cases where this may open up some very powerful features for distributed computing.  For example, a client could send a message to two destinations ('requests', '#worker003#srv001') as a multicast _and_ a unicast message.  This destination list shows up to _all_ recipients.  Very interesting.  Especially if you want to do replication or failover.

The other aspect of this, is that a message may be directed to multiple groups, and listeners on each group will know that a message has been "categorized" in some way.  For example, if there is a channel for "Events" and another channel for "Alerts", the same message may be directed to both channels when an Event is also an Alert.  A listener to just the "Events" channel would gain additional knowledge about this categorization just from the list of groups ["Events","Alerts"] that it sees on receipt of a new "Event" message.  Clearly, this could be abused all sorts of ways, so I'm not advocating using the destination group list as some crazy way of attaching metadata to every message.  But, in the legitimate cases where a message may be sent to multiple channels, this extra information may be quite useful.

On the annoying side of the protocol, the fact that the protocol doesn't align itself to a particular endian-ness is a pain.  I only have little-endian servers to test with, so I don't have proper endian correction code in place.  I'd rather not support it than write untestable code.  The message type (hint) field in particular is client-endianness, but the service type and length fields are all big-endian (network order).  It seems the goal of this endianness-preservation is to permit clients to send messages using their own endianness, and detect any endian-differences between others senders and themselves, for every single message, to permit an application to invoke different payload demarshalling code if it needs to do endian-swapping.  This logic for detecting client-client endian differences is also used on the service\_type field, to detect client-server endian differences too!  Clearly the server isn't likely to change endianness from packet to packet.  If anything, it should be a property of the connection that is established at connection time for client-server endianness differences.  Then every field of the header would have a known endianness, and the "message type" field could be endian-corrected by the server, saving bytes.  I think it's more likely than not that a spread network would consist of primarily similar endianness, and flipping bytes is cheap anyhow.  A single bit in each message header could indicate client-client endian differences, so the payload could be processed with different decoders and all would be happy.

Also, the 32-byte group name length is deeply etched into the protocol.  While I don't mind the idea of fixed-width group and client names, it makes for challenges if you choose to compile with a different value.  In an ideal world, I think the server should _provide_ the value of MAXGROUPLEN as part of the initial connection negotiation.  Then every client would be compatible, no matter what the value of MAXGROUPLEN.  At present, this value is hard coded in every client implementation, and in the server.  Changing it on the server requires changing every client API.  That seems like work that could be easily avoided with a negotiated max group length parameter.

The fixed-width group names really could be more efficiently encoded.  There is a notion of "group ID" which isn't documented very well, that might suit the purpose.  The API and the user guide documentation both treat group IDs as opaque values that have no internal structure.  It feels like the server-server protocol is leaking into the server-client side here, since you don't really _need_ to process these group IDs at all.  The group ID seems to be 3 int32 values.  Those would be a lot smaller on the wire for clients, but I'm not really complaining.  The 32 bytes which also encodes the source spread daemon's name isn't too high a price to pay, and it significantly simplifies the client API.

The client-server protocol has no keep alive messages.  This is pretty cool.  It means a client's TCP connection to a server can survive an hours-long network outage when there is no traffic in either direction, and as long as TCP KEEPALIVE is not enabled.  The flip side of this is that there are no acknowledgements for regular data messages, so a client could be connected to a spread daemon which is hung, without realizing it.  This is a problem for every asynchronous or asymmetric protocol, so it just needs a way to do an application-level ping.  Well, that's easy (and implemented now) by sending a message that is addressed to one's self using the private name as the destination group name.  This is _exactly_ the functionality that is needed, and it's nice that the spread fills that need perfectly.