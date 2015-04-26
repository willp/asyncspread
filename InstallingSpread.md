# Installation #

To build and install the Spread daemon, see the documentation at http://spread.org/download.html

# Sample Configuration #

If you are running spread on a local network, you will need to know your local IP address and subnet.  On most home networks, your local IP address will be part of a class-C subnet, which has a netmask of 255.255.255.0 also known as /24 subnet.  This sample configuration assumes you are running spread on a host with an IP in a class-C subnet.

Assuming your host has the following configuration:
  * IP Address: 192.168.1.202
  * Netmask: 255.255.255.0
  * A writable /var/run/spread/ directory (it won't be auto-created by spread, so you will need to mkdir this and have write permissions)

Here is a sample spread.conf file with all optional parameters omitted:
```
Spread_Segment  192.168.1.255:4803 {
     localhost  192.168.1.202
}
DebugFlags = { PRINT EXIT }

EventPriority =  INFO
EventTimeStamp = "[%a %d %b %Y %H:%M:%S]"
SocketPortReuse = ON
MaxSessionMessages = 5000
RuntimeDir = /var/run/spread
```

If your host's IP address is 10.1.2.57 with a netmask of 255.255.255.0, then you should change the Spread\_Segment line to use "10.1.2.255:4803" and change the "localhost" line to "10.1.2.57".

If you have multiple hosts in this subnet that each run spread (a great idea!), then eliminate the "localhost" line and instead use a single line with each hosts' true DNS hostname and IP within that shared subnet.  For more details, consult the Spread documentation.

# How To Run Spread With This Config #

This is how to run spread using this sample config:
```
%  ./daemon/spread -c sample.conf 
/===========================================================================\
| The Spread Toolkit.                                                       |
| Copyright (c) 1993-2009 Spread Concepts LLC                               |
| All rights reserved.                                                      |
|                                                                           |
| The Spread toolkit is licensed under the Spread Open-Source License.      |
| You may only use this software in compliance with the License.            |
| A copy of the license can be found at http://www.spread.org/license       |
|                                                                           |
| This product uses software developed by Spread Concepts LLC for use       |
| in the Spread toolkit. For more information about Spread,                 |
| see http://www.spread.org                                                 |
|                                                                           |
| This software is distributed on an "AS IS" basis, WITHOUT WARRANTY OF     |
| ANY KIND, either express or implied.                                      |
|                                                                           |
| Creators:                                                                 |
|    Yair Amir             yairamir@cs.jhu.edu                              |
|    Michal Miskin-Amir    michal@spreadconcepts.com                        |
|    Jonathan Stanton      jstanton@gwu.edu                                 |
|    John Schultz          jschultz@spreadconcepts.com                      |
|                                                                           |
| Major Contributors:                                                       |
|    Ryan Caudy           rcaudy@gmail.com - contribution to process groups.|
|    Claudiu Danilov      claudiu@acm.org - scalable, wide-area support.    |
|    Cristina Nita-Rotaru crisn@cs.purdue.edu - GC security.                |
|    Theo Schlossnagle    jesus@omniti.com - Perl, autoconf, old skiplist.  |
|    Dan Schoenblum       dansch@cnds.jhu.edu - Java interface.             |
|                                                                           |
| Special thanks to the following for discussions and ideas:                |
|    Ken Birman, Danny Dolev, Jacob Green, Mike Goodrich, Ben Laurie,       |
|    David Shaw, Gene Tsudik, Robbert VanRenesse.                           |
|                                                                           |
| Partial funding provided by the Defense Advanced Research Project Agency  |
| (DARPA) and the National Security Agency (NSA) 2000-2004. The Spread      |
| toolkit is not necessarily endorsed by DARPA or the NSA.                  |
|                                                                           |
| For a full list of contributors, see Readme.txt in the distribution.      |
|                                                                           |
| WWW:     www.spread.org     www.spreadconcepts.com                        |
| Contact: info@spreadconcepts.com                                          |
|                                                                           |
| Version 4.01.00 Built 18/June/2009                                        |
\===========================================================================/
Conf_load_conf_file: using file: sample.conf
Successfully configured Segment 0 [192.168.1.255:4803] with 1 procs:
                   localhost: 192.168.1.202
[Sat 15 Oct 2011 13:50:15] Setting SO_REUSEADDR to auto
[Sat 15 Oct 2011 13:50:15] Set runtime directory to '/var/run/spread'
Membership id is ( -1062731318, 1318711823)
[Sat 15 Oct 2011 13:50:22] --------------------
[Sat 15 Oct 2011 13:50:22] Configuration at localhost is:
[Sat 15 Oct 2011 13:50:22] Num Segments 1
[Sat 15 Oct 2011 13:50:22]      1       192.168.1.255     4803
[Sat 15 Oct 2011 13:50:22]              localhost               192.168.1.202   
[Sat 15 Oct 2011 13:50:22] ====================
```