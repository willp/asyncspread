# Requirements #

To run the example code, you must have:
  * a spread daemon running on a server that you can connect to
  * a computer with python 2.4+ installed.  (python 3.x is not supported well)
  * the asyncspread library and examples checked out from SVN or copied locally

(The asyncspread library has no extra dependencies other than stock python.  It does not use any external code other than what python already provides.)

# Examples #

Example code is available from the source repository in the trunk/examples/ subdirectory.

There currently only one example:
  * **Heartbeat Service**
    * hb\_server.py
    * hb\_client.py

# Heartbeat Service #

This example provides a distributed heartbeat service using a shared spread channel.

In general, a heartbeat service is a network accessible resource that a client sends a message to indicating the client is still alive.  The client may receive an acknowledgement from the server in response, though not every heartbeat service provides acknowledgements.  In this example, the heartbeat service sends an acknowledgement response to the client.

In this example, the spread daemon provides group communication between the heartbeat servers using a shared channel, and between the clients and servers using multicast (client => servers) and unicast responses (server => client).

Servers all connect to spread and join a shared channel.  Each server is notified when other servers join or leave this channel, so each has an identical view of the membership of the channel.  Clients connect to spread but do not join the channel.  Instead, clients send a message to the channel.  Spread then delivers this message to every server that has joined this channel.

The servers decide among themselves which one of themselves should process the message and send the acknowledgement to the client.  The servers use a shared calculation that uses their shared knowledge of the channel's group membership to reliably pick the _same_ server to be the responder.  That server then sends a unicast acknowledgement response to the client.

This example shows how the shared membership state among servers allows for a horizontally scalable distribution of work among the heartbeat servers.  When a new server is started and joins the shared channel, the workload is redistributed.

## How To Run the Heartbeat Example ##

First, ensure you have a working spread daemon to connect to.  You need its hostname (or IP address) and TCP port number.  The default port number for spread is 4803.  For instructions, see the InstallingSpread page.

Next, check out the trunk of the SVN repository for asyncspread from code.google.com:

```
%  svn checkout https://asyncspread.googlecode.com/svn/trunk asyncspread
[ ... snip ... ]
Checked out revision 176.
%  
%  cd asyncspread/examples
% ls
hb_client.py  hb_server.py
% 
```

Next, start up a single heartbeat server process,
```

% python hb_example.py servername 4803
I am: HBsrv-650
2011-10-15 09:30:16,604 ()- CRITICAL - AUTH METHODS: [u'NULL']
2011-10-15 09:30:16,705 ()- INFO - Server reports it is Spread version: 4.1.0
2011-10-15 09:30:16,705 ()- INFO - Spread session established to server:  localhost:4803
2011-10-15 09:30:16,705 ()- INFO - My private session name for this connection is: "#HBsrv-650#localhost"
Got connected: <asyncspread.connection.AsyncSpread>: name="HBsrv-650", connected=True, server="localhost:4803", session_name="#HBsrv-650#localhost", d/s=False/False
Joining the :HB channel...
hbs is: <asyncspread.connection.AsyncSpread>: name="HBsrv-650", connected=True, server="localhost:4803", session_name="#HBsrv-650#localhost", d/s=False/False
Joined the group (:HB).  Current # of HB servers: 1
Current members: set(['#HBsrv-650#localhost'])

```

Then, in another window, start up a single client instance:
```
%  python hb_client.py localhost 4803
I am HBcli-037
2011-10-15 09:31:40,476 ()- CRITICAL - AUTH METHODS: [u'NULL']
2011-10-15 09:31:40,577 ()- INFO - Server reports it is Spread version: 4.1.0
2011-10-15 09:31:40,577 ()- INFO - Spread session established to server:  localhost:4803
2011-10-15 09:31:40,577 ()- INFO - My private session name for this connection is: "#HBcli-037#localhost"
HBcli-037: client top of loop 0
HBcli-037: client top of loop 1
HBcli-037: client top of loop 2
HBcli-037: client top of loop 3
Got message: <class 'asyncspread.message.DataMessage'>:  sender:#HBsrv-650#localhost, mesg_type:1, groups:['#HBcli-037#localhost'], self-disc:False, data:"HB Reply:: 1 received, 1 sent"
HBcli-037: client top of loop 4
HBcli-037: client top of loop 5
HBcli-037: client top of loop 6

... etc ...
```

In the server's window, you will see:
```
I REPLY TO #HBcli-037#localhost  (0/0)
HBsrv-650>> HB message, type=0, sender="#HBcli-037#localhost", message: heartbeat ping from client
HBsrv-650>> sending reply!
I REPLY TO #HBcli-037#localhost  (0/0)
HBsrv-650>> HB message, type=0, sender="#HBcli-037#localhost", message: heartbeat ping from client
HBsrv-650>> sending reply!

```

Then, start up two more server processes, and watch the client's window to see how it receives a response from different servers as the hash calculation rebalances the workload among the servers.