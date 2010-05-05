#!/usr/bin/python2.4
import time, sys
sys.path.append('.')
import asyncspread
class MyListener(asyncspread.SpreadPingListener):
    def handle_ping(self, success, elapsed):
        print '***808 PONG:  Success:', success, ' Elapsed:', elapsed

    def handle_data(self, conn, mesg):
        print '*** Got message:', mesg.data

def ping_cb(success, elapsed):
    print '***707 PONG:  Success:', success, ' Elapsed:', elapsed
    #print  1 / 0

listener = MyListener() # asyncspread.SpreadListener()
myname = '\'%03d' % (int(time.time()*10) % 1000)
print 'My name is: "%s"' % myname
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999, listener=listener)
ret = sp.start_connect()

print 'Connected?', ret
if ret:
    print 'my private name is:',sp.private_name
for g in ('gr1', 'group2', 'gr2', 'gr5'):
    sp.join(g)
sp.loop(1)
for i in xrange(1, 35):
    if sp.dead:\
        break
    groups = ['gr1']
    if i % 5 == 0:
        groups.append('gr3')
        groups.append('gr5')
    if i % 6 == 0:
        sp.multicast(groups, '', ((i*101) % 65535))
    else:
        sp.multicast(groups, 'Test message number %d' % (i), ((i*100) % 0xffff))
    if i % 10 == 9:
        listener.ping(sp, ping_cb, 5)
    print 'sent off my messages for iteration %d' % (i)
    if i % 10 == 5:
        sp.join('gr1')
        sp.leave('gr2')
        sp.multicast(['gr1'], 'Just joined! i=%d' % (i), 0xff00)
    if i % 10 == 2:
        sp.leave('gr1')
        sp.join('gr2')
        sp.multicast(['gr1'], 'I have left! and I sent this AFTER i left! i=%d' % (i), 0x00ff)
    sp.loop(2)
    time.sleep(0.5)
sp.loop(10)
sp.leave('gr18')
sp.disconnect()
sp.loop(10)
sys.exit(0)
