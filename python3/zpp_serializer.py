import struct
import sys
import hashlib

class Uint64(int):
    tag = '<Q'

class Uint32(int):
    tag = '<I'

class Uint16(int):
    tag = '<H'

class Uint8(int):
    tag = '<B'

class Int64(int):
    tag = '<q'

class Int32(int):
    tag = '<i'

class Int16(int):
    tag = '<h'

class Int8(int):
    tag = 'b'

class Float(float):
    tag = '<f'

class Double(float):
    tag = '<d'

class Bool(int):
    tag = '?'

SizeType = Uint32

for kind in (Uint64, Uint32, Uint16, Uint8, Int64, Int32, Int16, Int8, Float, Double, Bool):
    kind.serialize = struct.Struct(kind.tag).pack
    kind.deserialize = struct.Struct(kind.tag).unpack
    kind.__zpp_member__ = len(kind.serialize(kind()))

def make_member(member_type, value):
    if hasattr(member_type, '__zpp_member__'):
        return member_type(value)

    if hasattr(member_type.__zpp_class__, 'container'):
        return member_type(value)

    if not isinstance(value, member_type):
        raise TypeError("Cannot convert from %s to %s." % (type(value).__name__, member_type.__name__))

    return value

class serializable(object):
    def __init__(self):
        self.previous_trace = sys.gettrace()
        sys.settrace(self.trace)

    def __call__(self, cls):
        def constructor(self, **kwargs):
            def initialize_bases(cls):
                for base in cls.__bases__:
                    if not hasattr(base, '__zpp_class__'):
                        continue

                    initialize_bases(base)

                    for name, member in base.__dict__.items():
                        if hasattr(member, '__zpp_member__') or hasattr(member, '__zpp_class__'):
                            object.__setattr__(self, name, member())

            initialize_bases(type(self))

            for base in type(self).__bases__:
                if not hasattr(base, '__zpp_class__'):
                    continue
                for name, member in base.__dict__.items():
                    if hasattr(member, '__zpp_member__'):
                        object.__setattr__(self, name, member())
                    elif hasattr(member, '__zpp_class__'):
                        object.__setattr__(self, name, member())
                
            for name, member in type(self).__dict__.items():
                if hasattr(member, '__zpp_member__'):
                    object.__setattr__(self, name, member())
                elif hasattr(member, '__zpp_class__'):
                    object.__setattr__(self, name, member())

            for name, value in kwargs.items():
                setattr(self, name, value)

        def assign(self, name, value):
            try:
                member = getattr(self, name)
                member_type = member
                if type(member_type) is not type:
                    member_type = type(member_type)
                return object.__setattr__(self, name, make_member(member_type, value))
            except AttributeError as error:
                raise TypeError("Type '%s' has no member named '%s'." % (type(self).__name__, name))

        def to_string(self, level=0, name=None):
            prefix = ' ' * level * 4
            if name:
                result = prefix + name + ": class " + type(self).__name__ + " {\n"
            else:
                result = prefix + "class " + type(self).__name__ + " {\n"
            level += 1
            prefix = ' ' * level * 4
            for name in self.__zpp_class__.members:
                member = getattr(self, name)
                if hasattr(member, '__zpp_member__'):
                    result += prefix + '%s: %s(%s),\n' % (name, type(member).__name__, member)
                elif hasattr(member, '__zpp_class__'):
                    result += member.__str__(level, name) + ',\n'
            level -= 1
            prefix = ' ' * level * 4
            result += prefix + '}'
            return result

        def serialize(self, archive):
            for name in self.__zpp_class__.members:
                archive(getattr(self, name))

        def deserialize(self, archive):
            for name in self.__zpp_class__.members:
                member = getattr(self, name)
                if hasattr(member, '__zpp_member__'):
                    setattr(self, name, archive(type(member)))
                elif hasattr(member, '__zpp_class__'):
                    archive(member)

        base_members = []
        for base in cls.__bases__:
            if hasattr(base, '__zpp_class__'):
                base_members += base.__zpp_class__.members

        members = dict(cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'members': base_members + [name for name in self.names if hasattr(cls, name)],
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__setattr__': assign,
            '__str__': to_string,
            })

        return type(cls.__name__, cls.__bases__, members)

    def trace(self, frame, event, argument):
        self.names = [name for name in frame.f_code.co_names if not name.startswith('_')]
        sys.settrace(self.previous_trace)

class polymorphic(serializable):
    registry = dict()

    def __init__(self, identifier):
        self.serialization_id = Uint64.deserialize(hashlib.sha1(identifier.encode('ascii')).digest()[:8])[0]
        super(polymorphic, self).__init__()

    def __call__(self, cls):
        def serialize(self, archive):
            archive(Uint64(self.__zpp_class__.serialization_id))
            for name in self.__zpp_class__.members:
                archive(getattr(self, name))

        def deserialize(archive):
            serialization_id = archive(Uint64)
            item = self.registry[serialization_id]()
            for name in item.__zpp_class__.members:
                member = getattr(item, name)
                if hasattr(member, '__zpp_member__'):
                    setattr(item, name, archive(type(member)))
                elif hasattr(member, '__zpp_class__'):
                    archive(member)
            return item

        cls = super(polymorphic, self).__call__(cls)
        cls.__zpp_class__.serialization_id = self.serialization_id
        cls.__zpp_class__.serialize = staticmethod(serialize)
        cls.__zpp_class__.deserialize = staticmethod(deserialize)
        self.registry[self.serialization_id] = cls
        return cls

class type_dependent(object):
    def __init__(self, cls):
        self.cls = cls

    def __call__(self, element):
        members = dict(self.cls.__dict__)
        members.update({
            'element': element
        })
        new_class = type(self.cls.__name__, self.cls.__bases__, members)
        return new_class

class type_and_size_dependent(object):
    def __init__(self, cls):
        self.cls = cls

    def __call__(self, element, size):
        members = dict(self.cls.__dict__)
        members.update({
            'element': element,
            'size': size
        })
        new_class = type(self.cls.__name__, self.cls.__bases__, members)
        return new_class

def printable_container(cls):
    def to_string(self, level=0, name=None):
        prefix = ' ' * level * 4
        if name:
            result = prefix + name + ": class " + type(self).__name__ + \
                '<' + self.element.__name__ + '>' + " {\n"
        else:
            result = prefix + "class " + type(self).__name__ + " {\n"
        level += 1
        prefix = ' ' * level * 4
        for index, item in enumerate(self.items):
            if hasattr(item, '__zpp_member__'):
                result += prefix + '[%s]: %s,\n' % (index, item)
            elif hasattr(item, '__zpp_class__'):
                result += item.__str__(level, name='[' + str(index) + ']') + ',\n'
        level -= 1
        prefix = ' ' * level * 4
        result += prefix + '}'
        return result

    members = dict(cls.__dict__)
    members.update({
        '__str__': to_string
    })
    new_class = type(cls.__name__, cls.__bases__, members)
    return new_class

@type_dependent
@printable_container
class Vector(object):
    class __zpp_class__(object):
        container = None

        @staticmethod
        def serialize(self, archive):
            archive(SizeType(len(self.items)))
            for item in self.items:
                archive(item)

        @staticmethod
        def deserialize(self, archive):
            size = archive(SizeType)
            self.items = [self.element() for index in range(size)]
            if hasattr(self.element, '__zpp_member__'):
                for index in range(size):
                    self.items[index] = archive(self.element)
            else:
                for item in self.items:
                    archive(item)

    def __init__(self, values=None):
        self.items = []
        if values:
            self.items = [make_member(self.element, value) for value in values]

    def __getitem__(self, index):
        return self.items[index]

    def __setitem__(self, index, value):
        if type(index) is slice:
            self.items[index] = [make_member(self.element, item) for item in value]
        else:
            self.items[index] = make_member(self.element, value)

@type_and_size_dependent
@printable_container
class Array(object):
    class __zpp_class__(object):
        container = None

        @staticmethod
        def serialize(self, archive):
            for item in self.items:
                archive(item)

        @staticmethod
        def deserialize(self, archive):
            self.items = [self.element() for index in range(self.size)]
            if hasattr(self.element, '__zpp_member__'):
                for index in range(self.size):
                    self.items[index] = archive(self.element)
            else:
                for item in self.items:
                    archive(item)

    def __init__(self, values=None):
        self.items = [self.element() for index in range(self.size)]
        if values:
            if len(values) != self.size:
                raise ValueError("Array size mismatch.")
            self.items = [make_member(self.element, value) for value in values]

    def __getitem__(self, index):
        return self.items[index]

    def __setitem__(self, index, value):
        if type(index) is slice:
            if index.stop > self.size:
                raise ValueError("This operation will adjust the length of the array.")
            self.items[index] = [make_member(self.element, item) for item in value]
        else:
            self.items[index] = make_member(self.element, value)

class String(object):
    class __zpp_class__(object):
        container = None

        @staticmethod
        def serialize(self, archive):
            archive(SizeType(len(self.items)))
            for item in self.items:
                archive(item)

        @staticmethod
        def deserialize(self, archive):
            size = archive(SizeType)
            self.items = [Uint8() for index in range(size)]
            for index in range(size):
                self.items[index] = archive(Uint8)

    def __init__(self, values=None):
        self.items = []
        if values:
            self.items = [Uint8(ord(value)) for value in values]

    def __getitem__(self, index):
        if type(index) is slice:
            return ''.join([chr(item) for item in self.items[index]])
        return chr(self.items[index])

    def __setitem__(self, index, value):
        if type(index) is slice:
            self.items[index] = [Uint8(ord(item)) for item in value]
        else:
            self.items[index] = Uint8(ord(value))

    def __str__(self, level=0, name=None):
        prefix = ' ' * level * 4
        string = ''.join([chr(item) for item in self.items])
        if not level:
            return string
        if name:
            result = prefix + name + ": class " + type(self).__name__ + \
                    "('" + string + "')"
        else:
            result = prefix + ": class " + type(self).__name__ + \
                    "('" + string + "')"
        return result

class MemoryOutputArchive(object):
    def __init__(self, data):
        self.data = data
        self.index = len(data)

    def __call__(self, *args):
        for item in args:
            if hasattr(item, '__zpp_member__'):
                serialized = item.serialize(item)
                self.data[self.index : self.index + len(serialized)] = serialized
                self.index += len(serialized)
            elif hasattr(item, '__zpp_class__'):
                item.__zpp_class__.serialize(item, self)

class MemoryInputArchive(object):
    def __init__(self, data):
        self.data = data
        self.index = 0

    def __call__(self, *args):
        if 1 == len(args):
            item = args[0]
            if hasattr(item, '__zpp_member__'):
                if type(item) is not type:
                    raise TypeError("Expected a class type.")
                size = item.__zpp_member__
                result = item.deserialize(self.data[self.index : self.index + size])[0]
                self.index += size
                return item(result)
            elif hasattr(item, '__zpp_class__') and hasattr(item.__zpp_class__, 'serialization_id'):
                if type(item) is not type:
                    raise TypeError("Expected a class type.")
                result = item.__zpp_class__.deserialize(self)
                if not isinstance(result, item):
                    raise ValueError("Deserialize type mismatch.")
                return result

        for item in args:
            item.__zpp_class__.deserialize(item, self)
