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

def make_function(name, code):
    environment = dict()
    environment.update(serialization_exports)
    exec(code, environment)
    return environment[name]

class SerializationGenerator(object):
    class Code(list):
        def __init__(self):
            super(SerializationGenerator.Code, self).__init__(self)
            self.level = 0
            self.tag = None

        def __iadd__(self, lines):
            self.tag = None
            new_lines = []
            for line in lines:
                for line in line.split('\n'):
                    new_lines += [''.join((' ' * 4 * self.level, line))]
            super(SerializationGenerator.Code, self).__iadd__(new_lines)
            return self

        def append_with_tag(self, tag, lines):
            result = self.__iadd__(lines)
            self.tag = tag
            return result

        def tag(self):
            return self.tag

    def __init__(self, cls, archive_type):
        if archive_type in output_archives:
            self.mode = 'serialize'
        elif archive_type in input_archives:
            self.mode = 'deserialize'
        else:
            raise TypeError("Invalid archive type.")

        self.function_name = '_'.join(('optimized', self.mode, cls.__name__))
        self.cls = cls
        self.archive_type = archive_type
        self.code = self.Code()
        self.code += [''.join(('def ', self.function_name, '(self, archive):'))]
        self.code.level += 1
        self.item_id = 0
        self.shortcut_id = 0
        self.index_id = 0
        self.archive_generator = self.archive_type.CodeGenerator(self.code)

    def generate_code(self):
        self.archive_generator.generate_start()
        self._generate_code(self.cls, 'self')
        self.archive_generator.generate_end()
        zpp_class = self.cls.__zpp_class__
        if self.mode == 'deserialize':
           if hasattr(zpp_class, 'serialization_id') or zpp_class.fundamental:
               self.code += ['return self']
        return ('_'.join((self.archive_type.name, self.mode)), self.make_function())

    def _item_id(self):
        item_id = self.item_id
        self.item_id += 1
        return item_id

    def _shortcut_id(self):
        shortcut_id = self.shortcut_id
        self.shortcut_id += 1
        return shortcut_id

    def _index_id(self):
        index_id = self.index_id
        self.index_id += 1
        return index_id

    def _generate_code(self, cls, variable_name):
        if not hasattr(cls, '__zpp_class__'):
            self.archive_generator.generate(cls, variable_name)
            return

        if cls.__zpp_class__.trivially_copyable:
            self.archive_generator.generate(cls, variable_name)
            return

        if cls.__zpp_class__.container:
            if not hasattr(cls.__zpp_class__, 'array_size'):
                if self.mode == 'serialize':
                    self._generate_code(SizeType,
                                       'SizeType(len({variable_name}))'.format(
                                           variable_name=variable_name))
                else:
                    self._generate_code(SizeType, 'container_size')

            if cls.element.__zpp_class__.trivially_copyable:
                context = type('context', (object,),
                               {'container_element_size': cls.element.__zpp_class__.size})
                return self.archive_generator.generate(bytearray,
                                                       '{variable_name}.data'.format(
                                                          variable_name=variable_name),
                                                       context=context)
            else:
                if self.mode == 'deserialize':
                    if hasattr(cls.element.__zpp_class__, 'serialization_id'):
                        index_name = '_'.join(('index', str(self._index_id())))
                        self.archive_generator.generate_enter_loop()
                        self.code += [
                            '{variable_name}.items = [None] * container_size' '\n'
                            'for {index} in xrange(container_size):'.format(
                                index=index_name)
                        ]
                        self.code.level += 1
                        self._generate_code(cls.element,
                                '{variable_name}[{index}]'.format(
                                    variable_name=variable_name,
                                    index=index_name))
                        self.code.level -= 1
                        self.index_id -= 1
                        self.archive_generator.generate_exit_loop()
                        return

                    if not hasattr(cls.__zpp_class__, 'array_size'):
                        self.code += [
                            '{variable_name}.items = '
                                'tuple({variable_name}.element() for i in xrange(container_size))'.format(
                                    variable_name=variable_name)
                        ]

                item_name = '_'.join(('item', str(self._item_id())))
                self.archive_generator.generate_enter_loop()
                self.code += [
                    'for {item} in {variable_name}:'.format(
                        variable_name=variable_name,
                        item=item_name)
                ]
                self.code.level += 1
                self._generate_code(cls.element, item_name)
                self.code.level -= 1
                self.archive_generator.generate_exit_loop()
                self.item_id -= 1
                return

        is_polymorphic = hasattr(cls.__zpp_class__, 'serialization_id')

        shortcut_set = False
        if '.' in variable_name and not (is_polymorphic and self.mode == 'deserialize'):
            shortcut_set = True
            shortcut = '_'.join(('current', str(self._shortcut_id())))
            self.code += [
                '{shortcut} = {variable_name}'.format(shortcut=shortcut,
                                                      variable_name=variable_name)
            ]
            variable_name = shortcut

        if hasattr(cls.__zpp_class__, 'serialization_id'):
            if self.mode == 'serialize':
                self._generate_code(Uint64,
                                   '{variable_name}.__zpp_class__.serialization_id'.format(
                                       variable_name=variable_name))
            else:
                self._generate_code(Uint64, 'serialization_id')
                self.archive_generator.generate_flush()
                self.code += [
                    '{variable_name} = registry[serialization_id]()' '\n'
                    '{variable_name}.{deserialize}({variable_name}, archive)'.format(
                        variable_name=variable_name,
                        deserialize='_'.join(('__zpp_class__.non_polymorphic',
                                              self.archive_type.name,
                                              'deserialize')))
                ]
                self.archive_generator.generate_reload()
                if shortcut_set:
                    self.shortcut_id -= 1
                return

        for member in cls.__zpp_class__.members:
            self._generate_code(getattr(cls, member),
                                '.'.join((variable_name, member)))
        if shortcut_set:
            self.shortcut_id -= 1

    def make_function(self):
        return make_function(self.function_name, '\n'.join(self.code))

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
        def constructor(self, *args, **kwargs):
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

            if args:
                if len(args) != 1:
                    raise TypeError("Invalid argument was sent.")
                item = args[0]
                for name in self.__zpp_class__.members:
                    if hasattr(item, name):
                        setattr(self, name, getattr(item, name))

            for name, value in kwargs.iteritems():
                setattr(self, name, value)

        def assign(self, name, value):
            try:
                member_type = getattr(type(self), name)
                return object.__setattr__(self, name, member_type.__zpp_class__.make(value))
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

        cls_members = base_members + derived_members

        members = dict(cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'members': cls_members,
                'fundamental': False,
                'container': False,
                'trivially_copyable': False,
            }),
            '__init__': constructor,
            '__setattr__': assign,
            '__getattribute__': object.__getattribute__,
            '__str__': to_string,
            '__repr__': to_string,
            })

        cls = type(cls.__name__, cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

    def trivially_copyable(self, cls, base_sizes, size, base_members, derived_members):
        def constructor(self, *args, **kwargs):
            if '__zpp_data__' in kwargs:
                object.__setattr__(self, '__zpp_data__', kwargs['__zpp_data__'])
            else:
                object.__setattr__(self, '__zpp_data__', bytearray(type(self).__zpp_class__.size))

            if args:
                if len(args) != 1:
                    raise TypeError("Invalid argument was sent.")
                item = args[0]
                for name in self.__zpp_class__.members:
                    if hasattr(item, name):
                        setattr(self, name, getattr(item, name))

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
                size = member_type.__zpp_class__.size
                return member_type(member_type.deserialize(
                    memoryview(self.__zpp_data__)[offset:offset+size])[0])
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
            if member_type.__zpp_class__.container and hasattr(value, '__len__'):
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
                'container': False,
                'trivially_copyable': True,
                'offsets': offsets,
                'size': size,
            }),
            '__init__': constructor,
            '__getattribute__': at,
            '__setattr__': assign,
            '__str__': to_string,
            '__repr__': to_string,
            })

        cls = type(cls.__name__, cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

    def trace(self, frame, event, argument):
        self.names = [name for name in frame.f_code.co_names if not name.startswith('_')]
        sys.settrace(self.previous_trace)

class polymorphic(serializable):
    registry = dict()

    def __init__(self, identifier):
        self.serialization_id = Uint64.deserialize(hashlib.sha1(identifier.encode('ascii')).digest()[:8])[0]
        super(polymorphic, self).__init__()

    def __call__(self, cls):
        cls = super(polymorphic, self).__call__(cls)
        cls.__zpp_class__.serialization_id = self.serialization_id
        cls.__zpp_class__.trivially_copyable = False

        cls = type(cls.__name__, cls.__bases__, dict(cls.__dict__))
        for output_archive in output_archives:
            function_name, function = SerializationGenerator(cls, output_archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        for input_archive in input_archives:
            function_name, function = SerializationGenerator(cls, input_archive).generate_code()
            setattr(cls.__zpp_class__, '_'.join(('non_polymorphic', function_name)),
                   staticmethod(getattr(cls.__zpp_class__, function_name)))
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        self.registry[self.serialization_id] = cls

        def make(value):
            if isinstance(value, cls):
                return type(value)(value)
            return cls(value)

        cls.__zpp_class__.make = staticmethod(make)
        cls.__zpp_class__.make_view = staticmethod(make)
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

            if values:
                self.items = [self.element.__zpp_class__.make(value) for value in values]
            else:
                self.items = [self.element() for index in range(size)]

        def at(self, index):
            return self.items[index]

        def assign(self, index, value):
            if type(index) is slice:
                self.items[index] = [self.element.__zpp_class__.make(item) for item in value]
            else:
                self.items[index] = self.element.__zpp_class__.make(value)

        def iterate(self):
            return (item for item in self.items)

        def size(self):
            return len(self.items)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'container': True,
                'trivially_copyable': False,
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })
        
        cls = type(self.cls.__name__, self.cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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
                            self.element.__zpp_class__.make_view(value).__zpp_data__

        def at(self, index):
            size = self.element.__zpp_class__.size
            return self.element(__zpp_data__=memoryview(self.data)[index * size : (index + 1) * size])

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.__zpp_class__.make_view(item).__zpp_data__
            else:
                self.data[index * size : (index + 1) * size] = \
                            self.element.__zpp_class__.make_view(value).__zpp_data__

        def iterate(self):
            for index in xrange(len(self.data) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.data) // self.element.__zpp_class__.size

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'container': True,
                'trivially_copyable': False,
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        cls = type(self.cls.__name__, self.cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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
                out(self.element.__zpp_class__.make_view(value))

        def at(self, index):
            size = self.element.__zpp_class__.size
            return self.element(self.element.deserialize(
                memoryview(self.data)[index * size : (index + 1) * size])[0])

        def assign(self, index, value):
            size = self.element.__zpp_class__.size
            if type(index) is slice:
                for i, item in enumerate(value):
                    self.data[(index.start + i) * size : (index.start + i + 1) * size] = \
                            self.element.serialize(self.element.__zpp_class__.make_view(item))
            else:
                self.data[index * size : (index + 1) * size] = \
                            self.element.serialize(self.element.__zpp_class__.make_view(value))

        def iterate(self):
            for index in xrange(len(self.data) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.data) // self.element.__zpp_class__.size

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'container': True,
                'trivially_copyable': False,
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        cls = type(self.cls.__name__, self.cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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
                self.items = [self.element.__zpp_class__.make(value) for value in values]
            else:
                self.items = [self.element() for index in xrange(array_size)]

        def at(self, index):
            return self.items[index]

        def assign(self, index, value):
            if type(index) is slice:
                if index.stop > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                self.items[index] = [self.element.__zpp_class__.make(item) for item in value]
            else:
                self.items[index] = self.element.__zpp_class__.make(value)

        def iterate(self):
            return (item for item in self.items)

        def size(self):
            return len(self.items)

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'container': True,
                'trivially_copyable': False,
                'array_size': array_size,
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        cls = type(self.cls.__name__, self.cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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
                            self.element.__zpp_class__.make_view(value).__zpp_data__

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
                            self.element.__zpp_class__.make_view(item).__zpp_data__
            else:
                if index > array_size:
                    raise ValueError("This operation will adjust the length of the array.")
                self.__zpp_data__[index * size : (index + 1) * size] = \
                            self.element.__zpp_class__.make_view(value).__zpp_data__

        def iterate(self):
            for index in xrange(len(self.__zpp_data__) // self.element.__zpp_class__.size):
                yield self[index]

        def size(self):
            return len(self.__zpp_data__) // self.element.__zpp_class__.size

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'container': True,
                'trivially_copyable': True,
                'size': array_size * element.__zpp_class__.size,
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        cls = type(self.cls.__name__, self.cls.__bases__, members)
        for archive in archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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
            size = self.element.__zpp_class__.size
            return self.element(self.element.deserialize(
                memoryview(self.__zpp_data__)[index * size : (index + 1) * size])[0])

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

        members = dict(self.cls.__dict__)
        members.update({
            '__zpp_class__': type('zpp_class', (object,), {
                'fundamental': False,
                'container': True,
                'trivially_copyable': True,
                'size': array_size * element.__zpp_class__.size,
            }),
            '__init__': constructor,
            '__getitem__': at,
            '__setitem__': assign,
            '__iter__': iterate,
            '__len__': size,
            'element': element,
        })

        cls = type(self.cls.__name__, self.cls.__bases__, members)
        for output_archive in output_archives:
            function_name, function = SerializationGenerator(cls, archive).generate_code()
            setattr(cls.__zpp_class__, function_name, staticmethod(function))

        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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
            size = self.element.__zpp_class__.size
            return self.character(self.element.deserialize(
                memoryview(self.data)[index * size : (index + 1) * size])[0])

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

        cls = type(name, cls.__bases__, members)
        cls.__zpp_class__.make = staticmethod(lambda value: cls(value))
        cls.__zpp_class__.make_view = staticmethod(lambda value: value if type(value) == cls else cls(value))
        return cls

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

class BasicMemoryArchiveCodeGenerator(object):
    def __init__(self, code):
        self.code = code
        self.index = 0
        self.loop = 0
        self.indices = []

    def generate_start(self):
        self.code += [
            'data = archive.data' '\n'
            'index = archive.index'
        ]

    def generate_end(self):
        index_string = ' '.join(('+', str(self.index)))
        self.code += [
            'archive.index = index{index}'.format(index=self._index_string())
        ]

    def generate_flush(self):
        self.code += [
            'archive.index = index{index}'.format(index=self._index_string())
        ]

    def generate_reload(self):
        self.code += [
            'index = archive.index'
        ]

    def generate_enter_loop(self):
        self.loop += 1
        self.indices.append(self.index)

    def generate_exit_loop(self):
        previous_index = self.indices.pop()
        self.loop -= 1
        self.code.level += 1
        if self.code.tag and 'index_addition_optimization' in self.code.tag:
            self.code.pop()
            expression, addition_immediate = self.code.tag['index_addition_optimization']
            addition_immediate += self.index - previous_index
            self.code += [
                'index += {expression}{difference}'.format(
                    expression=expression,
                    difference=self._difference_string(addition_immediate))
            ]
        else:
            self.code += [
                'index += {difference}'.format(difference=self.index-previous_index)
            ]
        self.index = previous_index
        self.code.level -= 1

    def _index_string(self):
        if self.index:
            return ' '.join((' +', str(self.index)))
        return ''

    def _index_plus_size_string(self, size):
        if self.index + size:
            return ' '.join((' +', str(self.index + size)))
        return ''

    def _difference_string(self, index):
        if index:
            return ' '.join((' +', str(index)))
        return ''

class MemoryOutputArchive(object):
    name = "memory"

    class CodeGenerator(BasicMemoryArchiveCodeGenerator):
        def __init__(self, code):
            super(MemoryOutputArchive.CodeGenerator, self).__init__(code)

        def generate(self, member_type, variable_name, context=None):
            if not hasattr(member_type, '__zpp_class__'):
                self.code.append_with_tag({'index_addition_optimization': ('size', self.index)}, [
                    'size = len({variable_name})' '\n'
                    'data[index{index} : index{index} + size] = {variable_name}' '\n'
                    'index += size{index}'.format(variable_name=variable_name,
                                                  index=self._index_string())
                ])
                self.index = 0
            elif member_type.__zpp_class__.fundamental:
                size = member_type.__zpp_class__.size
                self.code += [
                    'data[index{index} : index{index_plus_size}] = '
                        '{member_type}.serialize({variable_name})'.format(
                            variable_name=variable_name,
                            index=self._index_string(),
                            index_plus_size=self._index_plus_size_string(size),
                            member_type=member_type.__name__)
                ]
                self.index += size
            elif member_type.__zpp_class__.trivially_copyable:
                size = member_type.__zpp_class__.size
                self.code += [
                    'data[index{index} : index{index_plus_size}] = '
                        '{variable_name}.__zpp_data__'.format(
                            variable_name=variable_name,
                            index=self._index_string(),
                            index_plus_size=self._index_plus_size_string(size))
                ]
                self.index += size
            else:
                raise TypeError('Invalid argument of type %s.' % (member_type.__name__,))

    def __init__(self, data, index=None):
        self.data = data
        if index is not None:
            self.index = index
        else:
            self.index = len(data)

    def __call__(self, *args):
        for item in args:
            type(item).__zpp_class__.memory_serialize(item, self)

    def reset(self, index):
        self.index = index

class MemoryInputArchive(object):
    name = "memory"

    class CodeGenerator(BasicMemoryArchiveCodeGenerator):
        def __init__(self, code):
            super(MemoryInputArchive.CodeGenerator, self).__init__(code)

        def generate(self, member_type, variable_name, context=None):
            if context and hasattr(context, 'container_element_size'):
                self.code.append_with_tag({'index_addition_optimization': ('size', self.index)}, [
                    'size = container_size * {size}' '\n'
                    '{variable_name}[:] = '
                        'memoryview(data)[index{index} : index{index} + size]' '\n'
                    'index += size{index}'.format(variable_name=variable_name,
                                                  size=context.container_element_size,
                                                  index=self._index_string())
                ])
                self.index = 0
            elif not hasattr(member_type, '__zpp_class__'):
                self.code.append_with_tag({'index_addition_optimization': ('size', self.index)}, [
                    'size = len({variable_name})' '\n'
                    '{variable_name}[:] = '
                        'memoryview(data)[index{index} : index{index} + size]' '\n'
                    'index += size{index}'.format(variable_name=variable_name,
                                                  index=self._index_string())
                ])
                self.index = 0
            elif member_type.__zpp_class__.fundamental:
                size = member_type.__zpp_class__.size
                self.code += [
                    '{variable_name} = {member_type}({member_type}.deserialize('
                        'memoryview(data)[index{index} : index{index_plus_size}])[0])'.format(
                            variable_name=variable_name,
                            member_type=member_type.__name__,
                            index=self._index_string(),
                            index_plus_size=self._index_plus_size_string(size))
                ]
                self.index += size
            elif member_type.__zpp_class__.trivially_copyable:
                size = member_type.__zpp_class__.size
                self.code += [
                    '{variable_name}.__zpp_data__[:] = '
                        'memoryview(data)[index{index} : index{index_plus_size}]'.format(
                            variable_name=variable_name,
                            index=self._index_string(),
                            index_plus_size=self._index_plus_size_string(size))
                ]
                self.index += size
            else:
                raise TypeError('Invalid argument of type %s.' % (member_type.__name__,))

    def __init__(self, data, index=0):
        self.data = data
        self.index = index

    def __call__(self, *args):
        return tuple(item.__zpp_class__.memory_deserialize(item, self) for item in args) if \
            len(args) > 1 else args[0].__zpp_class__.memory_deserialize(args[0], self)

    def reset(self, index):
        self.index = index

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

serialization_exports = {}

for kind in (Uint64, Uint32, Uint16, Uint8, Int64, Int32, Int16, Int8, Float, Double, Bool):
    kind.serialize = struct.Struct(kind.tag).pack
    kind.deserialize = struct.Struct(kind.tag).unpack

    kind.__zpp_class__ = type('zpp_class', (object,), {
        'fundamental': True,
        'container': False,
        'trivially_copyable': True,
        'size': len(kind.serialize(kind())),
        'make': staticmethod(lambda value: kind(value)),
        'make_view': staticmethod(lambda value: kind(value)),
    })

SizeType = Uint32

serialization_exports = {
    'Uint64': Uint64,
    'Uint32': Uint32,
    'Uint16': Uint16,
    'Uint8': Uint8,
    'Int64': Int64,
    'Int32': Int32,
    'Int16': Int16,
    'Int8': Int8,
    'Float': Float,
    'Double': Double,
    'Bool': Bool,
    'SizeType': SizeType,
    'registry': polymorphic.registry
}

input_archives = (MemoryInputArchive,)
output_archives = (MemoryOutputArchive,)
archives = output_archives + input_archives

String = BasicString(Uint8)
WString = BasicString(Uint16)

for kind in (Uint64, Uint32, Uint16, Uint8, Int64, Int32, Int16, Int8, Float, Double, Bool):
    for archive in archives:
        function_name, function = SerializationGenerator(kind, archive).generate_code()
        setattr(kind.__zpp_class__, function_name, staticmethod(function))

