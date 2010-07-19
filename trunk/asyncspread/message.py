import logging
from services import ServiceTypes

class SpreadMessage(object):
    def _set_data(self, data):
        self.data = data

    def _set_grps(self, groups):
        self.groups = groups

class DataMessage(SpreadMessage):
    def __init__(self, sender, mesg_type, self_discarded):
        SpreadMessage.__init__(self)
        self.sender = sender
        self.mesg_type = mesg_type
        self.self_discarded = self_discarded
        self.groups = []
        self.data = ''

    def __repr__(self):
        return '%s:  sender:%s,  mesg_type:%d,  groups:%s,  self-disc:%s,  data:"%s"' % (self.__class__,
                            self.sender, self.mesg_type, self.groups, self.self_discarded, self.data)

class OpaqueMessage(SpreadMessage):
    def __init__(self, sender, svc_type, mesg_type, is_membership):
        SpreadMessage.__init__(self)
        self.sender = sender
        self.svc_type = svc_type
        self.mesg_type = mesg_type
        self.is_membership = is_membership
        self.groups = []
        self.data = ''

    def __repr__(self):
        return '%s:  svc_type: 0x%04x  mesg_type:%d  sender:%s  groups:%s  data(%d bytes):"%s"' % (self.svc_type,
                    self.mesg_type, self.__class__, self.sender, self.groups, len(self.data), self.data)

class MembershipMessage(SpreadMessage):
    def __init__(self, group):
        SpreadMessage.__init__(self)
        self.group = group
        self.members = []

    def _set_grps(self, groups):
        self.members = groups

    def __repr__(self):
        return '%s:  group:%s,  members:%s' % (self.__class__, self.group, self.members)

class TransitionalMessage(MembershipMessage):
    pass

class JoinMessage(MembershipMessage):
    pass

class DisconnectMessage(MembershipMessage):
    pass

class NetworkMessage(MembershipMessage):
    pass

class LeaveMessage(MembershipMessage):
    def __init__(self, group, self_leave=False):
        MembershipMessage.__init__(self, group)
        self.self_leave = self_leave

    def __repr__(self):
        return '%s:  group:%s,  self_leave:%s' % (self.__class__, self.group, self.self_leave)

class SpreadMessageFactory(object):
    '''Class to determine the kind of spread message and return an object that represents
    the message we received.  It is optimized for DataMessage types.'''
    def __init__(self):
        self._reset()
        self.logger = logging.getLogger()

    def _reset(self):
        self.this_mesg = None
        self.num_groups = 0
        self.mesg_len = 0

    def finish_message(self):
        mesg = self.this_mesg
        self._reset()
        return mesg

    def process_groups(self, groups):
        this_mesg = self.this_mesg
        assert this_mesg is not None, 'Message Factory invoked out of order.'
        this_mesg._set_grps(groups)
        return this_mesg

    def process_data(self, data):
        this_mesg = self.this_mesg
        assert this_mesg is not None, 'Message Factory invoked out of order.'
        this_mesg._set_data(data)
        return this_mesg

    def process_header(self, svc_type, mesg_type, sender, num_groups, mesg_len):
        self.num_groups = num_groups
        self.mesg_len = mesg_len
        if svc_type & ServiceTypes.REGULAR_MESS:
            # REGULAR message, we assume a regular message is never also a membership message
            self_discarded = svc_type & ServiceTypes.SELF_DISCARD != 0
            self.this_mesg = DataMessage(sender, mesg_type, self_discarded)
            return self.this_mesg
        if svc_type & ServiceTypes.REG_MEMB_MESS:
            # MEMBERSHIP messages
            if svc_type & ServiceTypes.TRANSITION_MESS:
                # TRANSITIONAL message, a type of membership message
                self.this_mesg = TransitionalMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_JOIN:
                self.this_mesg = JoinMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_LEAVE:
                self.this_mesg = LeaveMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_DISCONNECT:
                self.this_mesg = DisconnectMessage(sender)
                return self.this_mesg
            if svc_type & ServiceTypes.CAUSED_BY_NETWORK:
                self.this_mesg = NetworkMessage(sender)
                return self.this_mesg
            # fall-thru error here, unknown change-cause!
            self.logger.critical('Spread Protocol ERROR: Unknown membership change CAUSE. Unknown svc_type: 0x%04x' % (svc_type)) # TODO: raise exception?
            self.this_mesg = OpaqueMessage(sender, svc_type, mesg_type, is_membership=True)
            return self.this_mesg
        elif svc_type & ServiceTypes.CAUSED_BY_LEAVE:
            # self-LEAVE message
            self.this_mesg = LeaveMessage(sender, True)
            return self.this_mesg
        if svc_type & ServiceTypes.TRANSITION_MESS:
            # strange, sometimes this is received NOT as a regular membership message?
            # TRANSITIONAL message, usually it's a type of membership message
            self.this_mesg = TransitionalMessage(sender)
            # this might be perfectly normal behavior.  I left this logging.debug() call in here to see how often
            # it crops up in production.  There isn't really any error here, it's just something curious and probably
            # means that this TransitionalMessage is somehow different from a non-RegularMembership TransitionalMessage,
            # and I'd like to know (some day) what that difference really is, and do something with it, like store it as a boolean
            # in the TransitionalMessage object, so a client can do something meaningful with it.
            self.logger.debug('Spread Protocol: this transitional message was not marked as a Regular Membership Message. '
                'Svc_type:0x%04x  TransitionalMessage: %s' % (svc_type, self.this_mesg))
            return self.this_mesg
        # fall-thru error here, unknown type
        self.logger.critical('Spread Protocol ERROR: Unknown message type, neither DataMessage nor MembershipMessage bits set. Unknown svc_type=0x%04x' % (svc_type)) # TODO: raise exception?
        self.this_mesg = OpaqueMessage(sender, svc_type, mesg_type, is_membership=False)
        return self.this_mesg
        #return None

