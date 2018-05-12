import struct
import sys
import hashlib

__all__ = [
    'Uint64', 'Uint32', 'Uint16', 'Uint8',
    'Int64', 'Int32', 'Int16', 'Int8',
    'Float', 'Double', 'Bool',
    'serializable',
    'polymorphic',
    'Vector', 'Array', 'BasicString', 'String', 'WString',
    'MemoryInputArchive', 'MemoryOutputArchive'
    ]

class Uint64(long):
    tag = '<Q'

class Uint32(int):
    tag = '<I'

class Uint16(int):
    tag = '<H'

class Uint8(int):
    tag = '<B'

class Int64(long):
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
    kind.__zpp_class__ = type('zpp_class', (object,), {
        'fundamental': True,
        'trivially_copyable': True,
        'size': len(kind.serialize(kind())),
    })

def make_member(member_type, value):
    if type(value) == member_type:
        return value

    if member_type.__zpp_class__.fundamental:
        return member_type(value)

    if hasattr(member_type.__zpp_class__, 'container') and hasattr(value, '__len__'):
        return member_type(value)

    if hasattr(member_type.__zpp_class__, 'serialization_id') and isinstance(value, member_type):
        return value

    raise TypeError("Cannot convert from %s to %s." % (type(value).__name__, member_type.__name__))

class serializable(object):
    def __init__(self):
        self.previous_trace = sys.gettrace()
        sys.settrace(self.trace)

    def __call__(self, cls):
        base_members = tuple()
        trivially_copyable = True
        bases_size = 0
        for base in cls.__bases__:
            if hasattr(base, '__zpp_class__'):
                base_members += base.__zpp_class__.members
                if base.__zpp_class__.trivially_copyable:
                    bases_size += base.__zpp_class__.size
                else:
                    trivially_copyable = False

        derived_members = tuple(name for name in self.names \
                if hasattr(cls, name) and hasattr(getattr(cls, name), '__zpp_class__'))
        for derived_member in derived_members:
            derived_member = getattr(cls, derived_member)
            if not derived_member.__zpp_class__.trivially_copyable:
                trivially_copyable = False

        if trivially_copyable and not hasattr(self, 'serialization_id'):
            size = bases_size + sum(getattr(cls, derived_member).__zpp_class__.size \
                    for derived_member in derived_members)
            return self.trivially_copyable(cls, bases_size, size, base_members, derived_members)

        return self.non_trivially_copyable(cls, base_members, derived_members)

    def non_trivially_copyable(self, cls, base_members, derived_members):
        def constructor(self, **kwargs):
            def initialize_bases(cls):
                for base in cls.__bases__:
                    if not hasattr(base, '__zpp_class__'):
                        super(cls, self).__init__()
                        continue

                    initialize_bases(base)

                    for name, member in base.__dict__.iteritems():
                        if hasattr(member, '__zpp_class__'):
                            object.__setattr__(self, name, member())

            initialize_bases(type(self))

            for name, member in type(self).__dict__.iteritems():
                if hasattr(member, '__zpp_class__'):
                    object.__setattr__(self, name, member())

            for name, value in kwargs.iteritems():
                setattr(self, name, value)

        def assign(self, name, value):
            try:
                member_type = getattr(type(self), name)
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
                if member.__zpp_class__.fundamental:
                    result += prefix + '%s: %s(%s),\n' % (name, type(member).__name__, member)
                else:
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
                if member.__zpp_class__.fundamental:
                    setattr(self, name, archive(type(member)))
                else:
                    archive(member)

        cls_members = base_members + derived_members

        members = dict(cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'members': cls_members,
                'fundamental': False,
                'trivially_copyable': False,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__setattr__': assign,
            '__getattribute__': object.__getattribute__,
            '__str__': to_string,
            '__repr__': to_string,
            })

        return type(cls.__name__, cls.__bases__, members)

    def trivially_copyable(self, cls, base_sizes, size, base_members, derived_members):
        def constructor(self, **kwargs):
            if '__zpp_data__' in kwargs:
                object.__setattr__(self, '__zpp_data__', kwargs['__zpp_data__'])
            else:
                object.__setattr__(self, '__zpp_data__', bytearray(type(self).__zpp_class__.size))

            for name, value in kwargs.iteritems():
                setattr(self, name, value)

        def at(self, name):
            attribute = object.__getattribute__(self, name)
            if not hasattr(attribute, '__zpp_class__'):
                return attribute
            zpp_class = type(self).__zpp_class__
            if name not in zpp_class.offsets:
                return attribute
            member_type = attribute
            offset = zpp_class.offsets[name]
            if member_type.__zpp_class__.fundamental:
                return MemoryInputArchive(self.__zpp_data__, offset)(member_type)
            size = member_type.__zpp_class__.size
            return member_type(__zpp_data__=memoryview(self.__zpp_data__)[offset:offset+size])

        def assign(self, name, value):
            zpp_class = type(self).__zpp_class__
            if name not in zpp_class.unordered_members:
                return object.__setattr__(self, name, value)
            member_type = getattr(type(self), name)
            offset = zpp_class.offsets[name]
            size = member_type.__zpp_class__.size
            if member_type.__zpp_class__.fundamental:
                self.__zpp_data__[offset:offset+size] = member_type.serialize(member_type(value))
                return
            if hasattr(member_type.__zpp_class__, 'container') and hasattr(value, '__len__'):
                member_type(value, __zpp_data__=memoryview(self.__zpp_data__)[offset:offset+size])
                return
            if member_type != type(value):
                raise TypeError("Cannot convert from '%s' to '%s'." % (type(value), member_type))
            self.__zpp_data__[offset:offset+size] = value.__zpp_data__

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
                if member.__zpp_class__.fundamental:
                    result += prefix + '%s: %s(%s),\n' % (name, type(member).__name__, member)
                else:
                    result += member.__str__(level, name) + ',\n'
            level -= 1
            prefix = ' ' * level * 4
            result += prefix + '}'
            return result

        def serialize(self, archive):
            archive(self.__zpp_data__)

        def deserialize(self, archive):
            archive(self.__zpp_data__)

        cls_members = base_members + derived_members
        offsets = dict()
        offset = 0
        for member in cls_members:
            offsets[member] = offset
            offset += getattr(cls, member).__zpp_class__.size

        members = dict(cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'members': cls_members,
                'unordered_members': set(cls_members),
                'fundamental': False,
                'trivially_copyable': True,
                'offsets': offsets,
                'size': size,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getattribute__': at,
            '__setattr__': assign,
            '__str__': to_string,
            '__repr__': to_string,
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
                if member.__zpp_class__.fundamental:
                    setattr(item, name, archive(type(member)))
                else:
                    archive(member)
            return item

        cls = super(polymorphic, self).__call__(cls)
        cls.__zpp_class__.serialization_id = self.serialization_id
        cls.__zpp_class__.serialize = staticmethod(serialize)
        cls.__zpp_class__.deserialize = staticmethod(deserialize)
        cls.__zpp_class__.trivially_copyable = False
        self.registry[self.serialization_id] = cls
        return cls

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
        if self.element.__zpp_class__.fundamental:
            for index, item in enumerate(self):
                result += prefix + '[%s]: %s,\n' % (index, item)
        else:
            for index, item in enumerate(self):
                result += item.__str__(level, name='[' + str(index) + ']') + ',\n'
        level -= 1
        prefix = ' ' * level * 4
        result += prefix + '}'
        return result

    members = dict(cls.__dict__)
    members.update({
        '__str__': to_string,
        '__repr__': to_string,
    })
    new_class = type(cls.__name__, cls.__bases__, members)
    return new_class

class make_vector(object):
    def __init__(self, cls):
        self.cls = cls

    def __call__(self, element):
        if element.__zpp_class__.fundamental:
            return self.fundamental_vector(element)
        elif element.__zpp_class__.trivially_copyable:
            return self.trivially_copyable_vector(element)
        else:
            return self.vector(element)

    def vector(self, element):
        def constructor(self, *args, **kwargs):
            values = None
            size = 0
            if kwargs:
                if args:
                    raise TypeError("Vector initialized correctly")
                size = kwargs['size']
            elif args:
                if len(args) != 1:
                    raise TypeError("Vector initialized correctly")
                size = args[0]
                if hasattr(size, '__len__'):
                    values = size
                    size = len(values)

            self.items = [self.element() for index in xrange(size)]
            if values:
                self.items = [make_member(self.element, value) for value in values]

        def at(self, index):
            return self.items[index]

        def assign(self, index, value):
            if type(index) is slice:
                self.items[index] = [make_member(self.element, item) for item in value]
            else:
                self.items[index] = make_member(self.element, value)

        def iterate(self):
            return (item for item in self.items)

        def serialize(self, archive):
            archive(SizeType(len(self.items)))
            for item in self.items:
                archive(item)

        def deserialize(self, archive):
            size = archive(SizeType)
            self.items = [self.element() for index in xrange(size)]
            for item in self.items:
                archive(item)

        def size(self):
            return len(self.items)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'trivially_copyable': False,
                'container': None,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        return type(self.cls.__name__, self.cls.__bases__, members)

    def trivially_copyable_vector(self, element):
        def constructor(self, *args, **kwargs):
            values = []
            count = 0
            if kwargs:
                if args:
                    raise TypeError("Vector initialized correctly.")
                count = kwargs['size']
            elif args:
                if len(args) != 1:
                    raise TypeError("Vector initialized correctly.")
                count = args[0]
                if hasattr(count, '__len__'):
                    values = count
                    count = len(values)

            size = self.element.__zpp_class__.size
            self.data = bytearray(size * count)

            if values:
                for index, value in enumerate(values):
                    self.data[index * size : (index + 1) * size] = \
                            make_member(self.element, value).__zpp_data__

        def at(self, index):
            size = self.element.__zpp_class__.size
            return self.element(__zpp_data__=memoryview(self.data)[index * size : (index + 1) * size])

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            make_member(self.element, item).__zpp_data__
            else:
                self.data[index * size : (index + 1) * size] = \
                            make_member(self.element, value).__zpp_data__

        def iterate(self):
            for index in xrange(len(self.data) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.data) // self.element.__zpp_class__.size

        def serialize(self, archive):
            archive(SizeType(len(self.data) // self.element.__zpp_class__.size))
            archive(self.data)

        def deserialize(self, archive):
            size = archive(SizeType)
            self.data = bytearray(size * self.element.__zpp_class__.size)
            archive(self.data)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'trivially_copyable': False,
                'container': None,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        return type(self.cls.__name__, self.cls.__bases__, members)

    def fundamental_vector(self, element):
        def constructor(self, *args, **kwargs):
            values = []
            count = 0
            if kwargs:
                if args:
                    raise TypeError("Vector initialized correctly.")
                count = kwargs['size']
            elif args:
                if len(args) != 1:
                    raise TypeError("Vector initialized correctly.")
                count = args[0]
                if hasattr(count, '__len__'):
                    values = count
                    count = len(values)

            self.data = bytearray(count * self.element.__zpp_class__.size)
            out = MemoryOutputArchive(self.data, index=0)
            for value in values:
                out(make_member(self.element, value))

        def at(self, index):
            return MemoryInputArchive(self.data, index * self.element.__zpp_class__.size)(self.element)

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.serialize(make_member(self.element, item))
            else:
                self.data[index * size : (index + 1) * size] = \
                            self.element.serialize(make_member(self.element, value))

        def iterate(self):
            for index in xrange(len(self.data) // self.element.__zpp_class__.size):
                yield self[index]

        def serialize(self, archive):
            archive(SizeType(len(self.data) // self.element.__zpp_class__.size))
            archive(self.data)

        def deserialize(self, archive):
            size = archive(SizeType)
            self.data = bytearray(size * self.element.__zpp_class__.size)
            archive(self.data)

        def size(self):
            return len(self.data) // self.element.__zpp_class__.size

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'trivially_copyable': False,
                'container': None,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        return type(self.cls.__name__, self.cls.__bases__, members)

class make_array(object):
    def __init__(self, cls):
        self.cls = cls

    def __call__(self, element, size):
        if element.__zpp_class__.fundamental:
            return self.fundamental_array(element, size)
        elif element.__zpp_class__.trivially_copyable:
            return self.trivially_copyable_array(element, size)
        else:
            return self.array(element, size)

    def array(self, element, array_size):
        def constructor(self, values=None):
            if values:
                if len(values) != array_size:
                    raise ValueError("Array size mismatch.")
                self.items = [make_member(self.element, value) for value in values]
            else:
                self.items = [self.element() for index in xrange(array_size)]

        def at(self, index):
            return self.items[index]

        def assign(self, index, value):
            if type(index) is slice:
                if index.stop > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                self.items[index] = [make_member(self.element, item) for item in value]
            else:
                self.items[index] = make_member(self.element, value)

        def iterate(self):
            return (item for item in self.items)

        def serialize(self, archive):
            for item in self.items:
                archive(item)

        def deserialize(self, archive):
            for item in self.items:
                archive(item)

        def size(self):
            return len(self.items)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'trivially_copyable': False,
                'container': None,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        return type(self.cls.__name__, self.cls.__bases__, members)

    def trivially_copyable_array(self, element, array_size):
        def constructor(self, values=None, **kwargs):
            if kwargs:
                if '__zpp_data__' not in kwargs or len(kwargs) != 1:
                    raise ValueError("Invalid argument was sent.")
                self.__zpp_data__ = kwargs['__zpp_data__']
            else:
                self.__zpp_data__ = bytearray(array_size * self.element.__zpp_class__.size)

            if values:
                if len(values) != array_size:
                    raise ValueError("Array size mismatch.")
                size = self.element.__zpp_class__.size
                for index, value in enumerate(values):
                    self.__zpp_data__[index * size : (index + 1) * size] = \
                            make_member(self.element, value).__zpp_data__

        def at(self, index):
            size = self.element.__zpp_class__.size
            return self.element(__zpp_data__=memoryview(self.__zpp_data__)[index * size : (index + 1) * size])

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                if index.stop > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                for i, item in enumerate(value):
                    self.__zpp_data__[(index.start + i) * size : (index.start + i + 1) * size] = \
                            make_member(self.element, item).__zpp_data__
            else:
                if index > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                self.__zpp_data__[index * size : (index + 1) * size] = \
                            make_member(self.element, value).__zpp_data__

        def iterate(self):
            for index in xrange(len(self.__zpp_data__) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.__zpp_data__) // self.element.__zpp_class__.size

        def serialize(self, archive):
            archive(self.__zpp_data__)

        def deserialize(self, archive):
            archive(self.__zpp_data__)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'trivially_copyable': True,
                'size': array_size * element.__zpp_class__.size,
                'container': None,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        return type(self.cls.__name__, self.cls.__bases__, members)

    def fundamental_array(self, element, array_size):
        def constructor(self, values=None, **kwargs):
            if kwargs:
                if '__zpp_data__' not in kwargs or len(kwargs) != 1:
                    raise ValueError("Invalid argument was sent.")
                self.__zpp_data__ = kwargs['__zpp_data__']
            else:
                self.__zpp_data__ = bytearray(array_size * self.element.__zpp_class__.size)

            if values:
                if len(values) != array_size:
                    raise ValueError("Array size mismatch.")
                out = MemoryOutputArchive(self.__zpp_data__, index=0)
                for value in values:
                    out(self.element(value))

        def at(self, index):
            return MemoryInputArchive(self.__zpp_data__, index * self.element.__zpp_class__.size)(self.element)

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                if index.stop > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                for i, item in enumerate(value):
                    self.__zpp_data__[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.serialize(self.element(item))
            else:
                if index > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                self.__zpp_data__[index * size : (index + 1) * size] = \
                            self.element.serialize(self.element(value))

        def iterate(self):
            for index in xrange(len(self.__zpp_data__) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.__zpp_data__) // self.element.__zpp_class__.size

        def serialize(self, archive):
            archive(self.__zpp_data__)

        def deserialize(self, archive):
            archive(self.__zpp_data__)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'trivially_copyable': True,
                'size': array_size * element.__zpp_class__.size,
                'container': None,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        return type(self.cls.__name__, self.cls.__bases__, members)

class make_basic_string(object):
    def __init__(self, cls):
        self.cls = cls

    def __call__(self, element):
        cls = Vector(element)

        def constructor(self, values=[]):
            self.data = bytearray(len(values))
            out = MemoryOutputArchive(self.data, index=0)
            for value in values:
                out(self.element(ord(value)))

        def at(self, index):
            return self.character(MemoryInputArchive(self.data, index * self.element.__zpp_class__.size)(self.element))

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.serialize(self.element(ord(item)))
            else:
                self.data[index * size : (index + 1) * size] = \
                            self.element.serialize(self.element(ord(value)))

        def to_string(self, level=0, name=None):
            prefix = ' ' * level * 4
            string = self.data.decode(self.encoding)
            if not level:
                return string
            if name:
                result = prefix + name + ": class " + type(self).__name__ + \
                        "('" + string + "')"
            else:
                result = prefix + ": class " + type(self).__name__ + \
                        "('" + string + "')"
            return result

        members = dict(cls.__dict__)
        members.update({
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__str__': to_string,
            '__repr__': to_string,
            'encoding': 'ascii' if element.__zpp_class__.size == 1 else 'utf-16',
            'character': staticmethod(lambda value: (chr(value) if element.__zpp_class__.size == 1 else unichr(value)))
        })

        name = self.cls.__name__
        if element.__zpp_class__.size == 1:
            name = 'String'
        elif element.__zpp_class__.size == 2:
            name = 'WString'

        return type(name, cls.__bases__, members)

@make_vector
@printable_container
class Vector(object):
    pass

@make_array
@printable_container
class Array(object):
    pass

@make_basic_string
class BasicString(object):
    pass

String = BasicString(Uint8)
WString = BasicString(Uint16)

class MemoryOutputArchive(object):
    def __init__(self, data, index=None):
        self.data = data
        if index is not None:
            self.index = index
        else:
            self.index = len(data)

    def __call__(self, *args):
        for item in args:
            if not hasattr(item, '__zpp_class__'):
                self.data[self.index : self.index + len(item)] = item
                self.index += len(item)
            elif item.__zpp_class__.fundamental:
                serialized = item.serialize(item)
                self.data[self.index : self.index + len(serialized)] = serialized
                self.index += len(serialized)
            else:
                item.__zpp_class__.serialize(item, self)

    def reset(self, index):
        self.index = index

class MemoryInputArchive(object):
    def __init__(self, data, index=0):
        self.data = data
        self.index = index

    def __call__(self, *args):
        if 1 == len(args):
            item = args[0]
            if not hasattr(item, '__zpp_class__'):
                item[:] = self.data[self.index : self.index + len(item)]
                self.index += len(item)
                return

            if item.__zpp_class__.fundamental:
                if type(item) is not type:
                    raise TypeError("Expected a class type.")
                size = item.__zpp_class__.size
                result = item.deserialize(self.data[self.index : self.index + size])[0]
                self.index += size
                return item(result)

            if hasattr(item.__zpp_class__, 'serialization_id'):
                if type(item) is not type:
                    raise TypeError("Expected a class type.")
                result = item.__zpp_class__.deserialize(self)
                if not isinstance(result, item):
                    raise ValueError("Deserialize type mismatch.")
                return result

        for item in args:
            if type(item) is type:
                raise TypeError("Expected an object.")
            item.__zpp_class__.deserialize(item, self)

    def reset(self, index):
        self.index = index
