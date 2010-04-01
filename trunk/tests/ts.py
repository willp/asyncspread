#!/usr/bin/python

import asyncspread, time, sys

myname = 'srv-%s' % (int(time.time()) % 100)
sp = asyncspread.Spread(myname, '24999@%s' % (sys.argv[1]))
print 'my name is:', myname
sp.connect(priority_high=True)
sp.join(['gr1', 'group2', 'gr2'])
for i in xrange(1, 49):
    groups = ['gr1']
    if i % 10 == 0:
        groups.append('gr3')
        groups.append('gr4')
        groups.append('gr5')
    sp.multicast(groups, 'Test message number %d' % (i), ((i*100) % 65535))
    print 'sent off my messages for iteration %d' % (i)
    time.sleep(0.1)
    if i % 10 == 3:
        sp.join(['gr1'])
        sp.multicast(['gr1'], 'Just joined! i=%d' % (i), 0xff00)
    if i % 10 == 2:
        sp.leave(['gr1'])
        sp.multicast(['gr1'], 'I have left! and I sent this AFTER i left! i=%d' % (i), 0x00ff)
sp.leave(['gr1'])
sp.disconnect()
exit(0)
