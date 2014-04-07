# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2014 IBM Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This module implements client/server messages emitted from plugins.
# Things are defined here to 'encourage' developers to coordinate information
# format.  This is also how different data formats are supported
import confluent.exceptions as exc
import json


class ConfluentMessage(object):
    defaultvalue = ''
    defaulttype = 'text'

    def __init__(self):
        raise NotImplementedError("Must be subclassed!")

    def json(self):
        # This will create the canonical json representation of this message
        jsonsnippet = json.dumps(self.kvpairs, separators=(',', ':'))[1:-1]
        return jsonsnippet

    def raw(self):
        """Return pythonic representation of the response.

        Used by httpapi while assembling data prior to json serialization"""
        return self.kvpairs

    def strip_node(self, node):
        self.kvpairs = self.kvpairs[node]

    def html(self):
        #this is used to facilitate the api explorer feature
        snippet = ""
        for key in self.kvpairs.iterkeys():
            val = self.kvpairs[key]
            value = self.defaultvalue
            type = self.defaulttype
            notes = []
            if val is not None and 'value' in val:
                value = val['value']
                if 'inheritedfrom' in val:
                    notes.append('Inherited from %s' % val['inheritedfrom'])
                if 'expression' in val:
                    notes.append('Derived from expression "%s"' % val['expression'])
            elif val is not None and 'expression' in val and 'broken' in val:
                value = "*BROKEN*"
                notes.append('Derived from expression "%s"' % val['expression'])
                notes.append('Broken because of %s' % val['broken'])
            elif val is not None and 'expression' in val:
                value = val['expression']
            if value is None:
                value = ''
            if val is not None and value == '' and 'isset' in val and val['isset'] is True:
                # an encrypted value, put some *** to show it is set
                # in the explorer
                if 'inheritedfrom' in val:
                    notes.append('Inherited from %s' % val['inheritedfrom'])
                value = '********'
            if isinstance(val, list):
                snippet += key + ":"
                if len(val) == 0:
                    snippet += ('<input type="{0}" name="{1}" value="" '
                                ' "title="{2}">'
                                ).format(type, key, self.desc)
                for v in val:
                    snippet += ('<input type="{0}" name="{1}" value="{2}" '
                                ' "title="{3}">'
                                ).format(type, key, v, self.desc)
                snippet += (
                    '<input type="{0}" name="{1}" value="" title="{2}">'
                    '<input type="checkbox" name="restexplorerhonorkey" '
                    'value="{1}">').format(type, key, self.desc)
                return snippet
            snippet += (key + ":" +
                        '<input type="{0}" name="{1}" value="{2}" '
                        'title="{3}"><input type="checkbox" '
                        'name="restexplorerhonorkey" value="{1}">'
                        ).format(type, key, value, self.desc)
            if len(notes) > 0:
                snippet += '(' + ','.join(notes) + ')'
        return snippet


class DeletedResource(ConfluentMessage):
    def __init__(self, resource):
        self.kvpairs = {}


class ConfluentChoiceMessage(ConfluentMessage):

    def html(self):
        snippet = ""
        for key in self.kvpairs.iterkeys():
            val = self.kvpairs[key]
            snippet += key + ':<select name="%s">' % key
            for opt in self.valid_values:
                snippet += opt + ":"
                if opt == val['value']:
                    snippet += '<option value="%s" selected>%s</option>' % (
                        opt, opt)
                else:
                    snippet += '<option value="%s">%s</option>' % (opt, opt)
            snippet += '</select>'
            snippet += '<input type="checkbox" name="restexplorerhonorkey" '
            snippet += 'value="%s">' % (key)
        return snippet


class LinkRelation(ConfluentMessage):
    def json(self):
        """Provide json_hal style representation of the relation.

        This currently only makes sense for the socket api.
        """
        return {self.rel: '{ "href": "%s" }' % self.href}

    def raw(self):
        """Provide python structure of the relation.

        This currently is only sensible to consume from httpapi.
        """
        return {self.rel: {"href": self.href}}

    def html(self):
        """Provide an html representation of the link relation.

        This is used by the API explorer aspect of httpapi"""
        return '<a href="{0}" rel="{1}">{0}</a>'.format(self.href, self.rel)
        # return '<a href="%s" rel="%s">%s</a><input type="submit"
        # name="restexprerorop" value="delete:%s"' % (self.href, self.rel,
        # self.href, self.href)


class ChildCollection(LinkRelation):
    def __init__(self, collname, candelete=False):
        self.rel = 'item'
        self.href = collname
        self.candelete = candelete

    def html(self):
        if self.candelete:
            return ('<a href="{0}" rel="{1}">{0}</a> . . . . . . . . . . . . '
                    '<button type="submit" name="restexplorerop" '
                    'value="delete" formaction="{0}">delete'
                    '</button>').format(self.href, self.rel)
        else:
            return '<a href="{0}" rel="{0}">{0}</a>'.format(self.href)


def get_input_message(path, operation, inputdata, nodes=None):
    if path[0] == 'power' and path[1] == 'state' and operation != 'retrieve':
        return InputPowerMessage(path, nodes, inputdata)
    elif path[0] == 'attributes' and operation != 'retrieve':
        return InputAttributes(path, inputdata, nodes)
    elif path == ['boot', 'nextdevice'] and operation != 'retrieve':
        return InputBootDevice(path, nodes, inputdata)
    elif inputdata:
        raise exc.InvalidArgumentException()


class InputAttributes(ConfluentMessage):

    def __init__(self, path, inputdata, nodes=None):
        self.nodeattribs = {}
        nestedmode = False
        if not inputdata:
            raise exc.InvalidArgumentException
        if nodes is None:
            self.attribs = inputdata
            for attrib in self.attribs:
                if type(self.attribs[attrib]) in (str, unicode):
                    try:
                        # ok, try to use format against the string
                        # store back result to the attribute to
                        # handle things like '{{' and '}}'
                        # if any weird sort of error should
                        # happen, it means the string has something
                        # that formatter is looking to fulfill, but
                        # is unable to do so, meaning it is an expression
                        tv = self.attribs[attrib].format()
                        self.attribs[attrib] = tv
                    except:
                        # this means format() actually thought there was work
                        # that suggested parameters, push it in as an
                        # expression
                        self.attribs[attrib] = {
                            'expression': self.attribs[attrib]}
            return
        for node in nodes:
            if node in inputdata:
                nestedmode = True
                self.nodeattribs[node] = inputdata[node]
        if nestedmode:
            for key in inputdata:
                if key not in nodes:
                    raise exc.InvalidArgumentException
        else:
            for node in nodes:
                self.nodeattribs[node] = inputdata

    def get_attributes(self, node):
        if node not in self.nodeattribs:
            return {}
        nodeattr = self.nodeattribs[node]
        for attr in nodeattr:
            if type(nodeattr[attr]) in (str, unicode):
                try:
                    # as above, use format() to see if string follows
                    # expression, store value back in case of escapes
                    tv = nodeattr[attr].format()
                    nodeattr[attr] = tv
                except:
                    # an expression string will error if format() done
                    # use that as cue to put it into config as an expr
                    nodeattr[attr] = {'expression': nodeattr[attr]}
        return nodeattr


class InputPowerMessage(ConfluentMessage):
    valid_values = set([
        'on',
        'off',
        'reset',
        'boot',
        ])

    def __init__(self, path, nodes, inputdata):
        self.powerbynode = {}
        if not inputdata:
            raise exc.InvalidArgumentException()
        if 'state' not in inputdata:
            #assume we have nested information
            for key in nodes:
                if key not in inputdata:
                    raise exc.InvalidArgumentException()
                datum = inputdata[key]
                if ('state' not in datum or
                        datum['state'] not in self.valid_values):
                    raise exc.InvalidArgumentException()
                self.powerbynode[key] = datum['state']
        else:  # we have a state argument not by node
            datum = inputdata
            if ('state' not in datum or
                    datum['state'] not in self.valid_values):
                raise exc.InvalidArgumentException()
            for node in nodes:
                self.powerbynode[node] = datum['state']

    def powerstate(self, node):
        return self.powerbynode[node]


class BootDevice(ConfluentChoiceMessage):
    valid_values = set([
        'network',
        'hd',
        'setup',
        'default',
        'cd',
        ])

    def __init__(self, node, device):
        if device not in self.valid_values:
            raise Exception("Invalid boot device argument passed in:" + device)
        self.kvpairs = {
            node: {
                'nextdevice': {'value': device},
            }
        }


class InputBootDevice(BootDevice):
    def __init__(self, path, nodes, inputdata):
        self.bootdevbynode = {}
        if not inputdata:
            raise exc.InvalidArgumentException()
        if 'nextdevice' not in inputdata:
            for key in nodes:
                if key not in inputdata:
                    raise exc.InvalidArgumentException()
                datum = inputdata[key]
                if ('state' not in datum or
                        datum['state'] not in self.valid_values):
                    raise exc.InvalidArgumenTException()
                self.bootdevbynode[key] = datum['nextdevice']
        else:
            datum = inputdata
            if ('nextdevice' not in datum or
                    datum['nextdevice'] not in self.valid_values):
                raise exc.InvalidArgumentException()
            for node in nodes:
                self.bootdevbynode[node] = datum['nextdevice']

    def bootdevice(self, node):
        return self.bootdevbynode[node]


class PowerState(ConfluentChoiceMessage):
    valid_values = set([
        'on',
        'off',
        'reset',
        'boot',
        ])

    def __init__(self, node, state):
        self.kvpairs = {
            node: {
                'state': {'value': state},
            }
        }


class Attributes(ConfluentMessage):
    def __init__(self, node=None, kv=None, desc=''):
        self.desc = desc
        nkv = {}
        for key in kv.iterkeys():
            if type(kv[key]) in (str, unicode):
                nkv[key] = {'value': kv[key]}
            else:
                nkv[key] = kv[key]
        if node is None:
            self.kvpairs = nkv
        else:
            self.kvpairs = {
                node: nkv
            }


class ListAttributes(ConfluentMessage):
    def __init__(self, node=None, kv=None, desc=''):
        self.desc = desc
        if node is None:
            self.kvpairs = kv
        else:
            self.kvpairs = {node: kv}


class CryptedAttributes(Attributes):
    defaulttype = 'password'

    def __init__(self, node=None, kv=None, desc=''):
        # for now, just keep the dictionary keys and discard crypt value
        self.desc = desc
        nkv = {}
        for key in kv.iterkeys():
            nkv[key] = {'isset': False}
            try:
                if kv[key] is not None and kv[key]['cryptvalue'] != '':
                    nkv[key] = {'isset': True}
                    nkv[key]['inheritedfrom'] = kv[key]['inheritedfrom']
            except KeyError:
                pass
        if node is None:
            self.kvpairs = nkv
        else:
            self.kvpairs = {
                node: nkv
            }
