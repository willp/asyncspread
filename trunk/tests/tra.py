#!/usr/bin/python2.4

import asyncspread, time, sys

myname = 'cli-%s' % (int(time.time()*10) % 1000)
print 'I am', myname
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999)
sp.loop(0.1)
sp.join(['gr1', 'gr2', 'abc123', 'def'])
sp.loop()

#sp.connect()
#sp.join(['gr1', 'gr2', 'gr3', 'group1', 'group2', 'group3'])
#sp.multicast([sp.private_name], 'Message to myself %f' % (time.time()), 0)
#i = 0
#while True:
#    i += 1
#    print '      ',sp.receive()

