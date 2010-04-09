#!/usr/bin/python
import asyncspread, time, sys

def ping_cb(success, elapsed):
    print '*** PONG:  Success:', success, ' Elapsed:', elapsed

def mesg_cb(mesg):
    print '*** Got message:', mesg.data

def g3_cb(mesg):
    print '*** g3 got callback data:\n::', mesg.data, '\nwhich was sent to groups::', mesg.groups

myname = 'ts-%s' % (int(time.time()*10) % 1000)
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999, cb_data=mesg_cb, debug=False)
sp.add_group_callback('gr3', g3_cb)
ret = sp.start_connect()

print 'Connected?', ret
print 'my private name is:',sp.private_name
sp.join(['gr1', 'group2', 'gr2'])
sp.loop(1)
for i in xrange(1, 25):
    groups = ['gr1']
    if i % 5 == 0:
        groups.append('gr3')
        groups.append('gr4')
        groups.append('gr5')
    if i % 6 == 0:
        sp.multicast(groups, '', ((i*101) % 65535))
    else:
        sp.multicast(groups, 'Test message number %d' % (i), ((i*100) % 65535))
    if i % 10 == 9:
        sp.ping(ping_cb, 5)
    print 'sent off my messages for iteration %d' % (i)
    if i % 10 == 3:
        sp.join(['gr1'])
        sp.multicast(['gr1'], 'Just joined! i=%d' % (i), 0xff00)
    if i % 10 == 2:
        sp.leave(['gr1'])
        sp.multicast(['gr1'], 'I have left! and I sent this AFTER i left! i=%d' % (i), 0x00ff)
    sp.loop(2)
    time.sleep(1)
sp.loop(10)
sp.leave(['gr1'])
sp.disconnect()
sp.loop(10)
exit(0)
