#!/usr/bin/python

import asyncspread, time, sys

myname = 'srv-%s' % (int(time.time()*10) % 1000)
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999)
ret = sp.wait_for_connection(10)
print 'Connected?', ret
print 'my private name is:',sp.private_name
sp.join(['gr1', 'group2', 'gr2'])
for i in xrange(1, 49):
    sp.poll(30)
    time.sleep(1)
    groups = ['gr1']
    if i % 10 == 0:
        groups.append('gr3')
        groups.append('gr4')
        groups.append('gr5')
    sp.multicast(groups, 'Test message number %d' % (i), ((i*100) % 65535))
    print 'sent off my messages for iteration %d' % (i)
    if i % 10 == 3:
        sp.join(['gr1'])
        sp.multicast(['gr1'], 'Just joined! i=%d' % (i), 0xff00)
    if i % 10 == 2:
        sp.leave(['gr1'])
        sp.multicast(['gr1'], 'I have left! and I sent this AFTER i left! i=%d' % (i), 0x00ff)
sp.loop(10)
sp.leave(['gr1'])
sp.disconnect()
sp.loop(10)
exit(0)
