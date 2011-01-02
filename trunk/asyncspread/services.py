import struct

class ServiceTypes(object):
    '''Spread Service Types and protocol values
    implemented as class-scoped enumerated values.'''
    UNRELIABLE_MESS = 0x00000001
    RELIABLE_MESS = 0x00000002
    FIFO_MESS  = 0x00000004
    CAUSAL_MESS = 0x00000008
    AGREED_MESS = 0x00000010
    SAFE_MESS  = 0x00000020

    # Message Actions
    JOIN = 0x00010000
    LEAVE = 0x020000
    KILL = 0x00040000

    SEND = SAFE_MESS
    SELF_DISCARD = 0x00000040 # A flag to disable refelction back of one's own message
    SEND_NOREFLECT = SEND | SELF_DISCARD

    # Message Types
    REGULAR_MESS = 0x0000003f
    REG_MEMB_MESS = 0x00001000
    TRANSITION_MESS = 0x00002000
    MEMBERSHIP_MESS = 0x00003f00

    # Membership Change Reasons
    CAUSED_BY_JOIN = 0x00000100
    CAUSED_BY_LEAVE = 0x00000200
    CAUSED_BY_DISCONNECT = 0x00000400
    CAUSED_BY_NETWORK = 0x00000800

def _make_group_formats(max_groups, max_group_len=32):
    group_fmt = '%ds' % max_group_len
    return [ group_fmt * i for i in range(max_groups) ]

### TODO: Scope problems here in these class-level values.  Python3 won't preserve the locals in the list comprehension for GROUP_FMTS
class SpreadProto(object):
    MAX_GROUP_LEN = 32
    GROUP_FMT = '%ds' % (MAX_GROUP_LEN)
    HEADER_FMT = 'I%ssIII' % (MAX_GROUP_LEN)

    (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH) = (4, 1, 0)

    # Pre-create some format strings
    # Don't send to more than MAX_GROUPS groups at once, increase if necessary
    MAX_GROUPS = 1000
    # This list will consume 1000*3 = 3 KB, plus overhead.  Worth it to spend the RAM.
    #GROUP_FMTS = [ GROUP_FMT * i for i in range(MAX_GROUPS) ]
    GROUP_FMTS = _make_group_formats(MAX_GROUPS, MAX_GROUP_LEN)

    # Encoded message headers
    JOIN_PKT = struct.pack('!I', ServiceTypes.JOIN)
    LEAVE_PKT = struct.pack('!I', ServiceTypes.LEAVE)
    KILL_PKT = struct.pack('!I', ServiceTypes.KILL)

    # Handshake message parts
    AUTH_PKT = struct.pack('90s', 'NULL')

    def __init__(self):
        self.set_level()

    def set_level(self, default_type=ServiceTypes.AGREED_MESS):
        self.default_type = default_type
        self.send_pkt = struct.pack('!I', default_type)
        self.send_pkt_selfdisc = struct.pack('!I', default_type | ServiceTypes.SELF_DISCARD)

    @staticmethod
    def protocol_create(service_type, mesg_type, session_name, group_names, data_len=0):
        #print 'protocol_create(len(service_type)=%d, mesg_type=%s, session_name=%s, group_names=%s, data_len=%d)' % (len(service_type),
        #       mesg_type, session_name, group_names, data_len)
        mesg_type_str = struct.pack('<I', (mesg_type & 0xffff) << 8)
        session_name = str(session_name)
        msg_hdr = struct.pack('>32sI4sI', session_name, len(group_names), mesg_type_str, data_len)
        grp_tag  = SpreadProto.GROUP_FMTS[len(group_names)] # '32s' * len(gname)
        grp_hdr = struct.pack(grp_tag, *group_names)
        #header = ''.join((service_type, msg_hdr, grp_hdr))
        header = service_type + msg_hdr + grp_hdr
        return header

    @staticmethod
    def protocol_connect(my_name, membership_notifications=True, priority_high=False):
        name_len = len(my_name)
        mem_opts = 0x00
        if membership_notifications:
            mem_opts |= 0x01
        if priority_high:
            mem_opts |= 0x10
        connect_fmt = '!5B%ds' % name_len
        #print 'connect_fmt:', connect_fmt, 'args', (4, 1, 0, mem_opts, name_len, my_name)
        return struct.pack(connect_fmt, SpreadProto.VERSION_MAJOR, SpreadProto.VERSION_MINOR, SpreadProto.VERSION_PATCH, mem_opts, name_len, my_name)

    def get_send_pkt(self, self_discard):
        if self_discard:
            return self.send_pkt_selfdisc
        return self.send_pkt
