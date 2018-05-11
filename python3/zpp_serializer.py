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
    kind.__zpp_class__ = type('zpp_class', (object,), {
        'fundamental': True,
        'size': len(kind.serialize(kind())),
    })

def make_member(member_type, value):
    if member_type.__zpp_class__.fundamental:
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
                        if hasattr(member, '__zpp_class__'):
                            object.__setattr__(self, name, member())

            initialize_bases(type(self))

            for base in type(self).__bases__:
                if not hasattr(base, '__zpp_class__'):
                    continue
                for name, member in base.__dict__.items():
                    if hasattr(member, '__zpp_class__'):
                        object.__setattr__(self, name, member())

            for name, member in type(self).__dict__.items():
                if hasattr(member, '__zpp_class__'):
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

        base_members = []
        for base in cls.__bases__:
            if hasattr(base, '__zpp_class__'):
                base_members += base.__zpp_class__.members

        members = dict(cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'members': base_members + [name for name in self.names if hasattr(cls, name)],
                'fundamental': False,
                'serialize': staticmethod(serialize),
                'deserialize': staticmethod(deserialize),
            }),
            '__init__': constructor,
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
            return self.optimized_vector(element)
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

            self.items = [self.element() for index in range(size)]
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
            self.items = [self.element() for index in range(size)]
            for item in self.items:
                archive(item)

        def size(self):
            return len(self.items)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
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

    def optimized_vector(self, element):
        def constructor(self, *args, **kwargs):
            values = []
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

            self.data = bytearray(size)
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
            for index in range(len(self.data) // self.element.__zpp_class__.size):
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
            return self.optimized_array(element, size)
        else:
            return self.array(element, size)

    def array(self, element, array_size):
        def constructor(self, values=None):
            if values:
                if len(values) != array_size:
                    raise ValueError("Array size mismatch.")
                self.items = [make_member(self.element, value) for value in values]
            else:
                self.items = [self.element() for index in range(array_size)]

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

    def optimized_array(self, element, array_size):
        def constructor(self, values=None):
            self.data = bytearray(array_size * self.element.__zpp_class__.size)
            if values:
                if len(values) != array_size:
                    raise ValueError("Array size mismatch.")
                out = MemoryOutputArchive(self.data, index=0)
                for value in values:
                    out(make_member(self.element, value))

        def at(self, index):
            return MemoryInputArchive(self.data, index * self.element.__zpp_class__.size)(self.element)

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                if index.stop > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.serialize(make_member(self.element, item))
            else:
                if index > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                self.data[index * size : (index + 1) * size] = \
                            self.element.serialize(make_member(self.element, value))

        def iterate(self):
            for index in range(len(self.data) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.data) // self.element.__zpp_class__.size

        def serialize(self, archive):
            archive(self.data)

        def deserialize(self, archive):
            archive(self.data)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
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
                out(make_member(self.element, ord(value)))

        def at(self, index):
            return chr(MemoryInputArchive(self.data, index * self.element.__zpp_class__.size)(self.element))

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.serialize(make_member(self.element, ord(item)))
            else:
                self.data[index * size : (index + 1) * size] = \
                            self.element.serialize(make_member(self.element, ord(value)))

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
