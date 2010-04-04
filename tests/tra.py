#!/usr/bin/python2.4

import asyncspread, time, sys

myname = 'cli-%06d' % (int(time.time()*100) % 1000)
print 'I am', myname
#myname = ''
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999)
sp.start_connect()
sp.join(['gr1', 'gr2', 'abc123', 'def'])
while True:
    print 'client top of loop'
    sp.ping()
    sp.loop(100)

#sp.connect()
#sp.join(['gr1', 'gr2', 'gr3', 'group1', 'group2', 'group3'])
#sp.multicast([sp.private_name], 'Message to myself %f' % (time.time()), 0)
#i = 0
#while True:
#    i += 1
#    print '      ',sp.receive()

