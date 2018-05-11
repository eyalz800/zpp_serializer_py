zpp_serializer_py
=================
The python version of zpp serializer, to be found here: https://github.com/eyalz800/serializer.

Abstract
--------
This is a simple python 2.7/3+ script that is compatible with the aforementioned C++ serialization framework
above. For more info, please read the description there.

Example
-------
This example is similar to the C++ example you can find at the link
above, essentially allowing the C++ version to communicate with the python
version and vice versa.
Note: the examples are written in python 2.7.

```py
import sys
import zpp_serializer

@zpp_serializer.serializable()
class Point(object):
    x = zpp_serializer.Int32
    y = zpp_serializer.Int32

@zpp_serializer.polymorphic('v1::person')
class Person(object):
    name = zpp_serializer.String

    def print_me(self):
        print "person: " + str(self.name)

@zpp_serializer.polymorphic('v1::student')
class Student(Person):
    university = zpp_serializer.String

    def print_me(self):
        print "student: " + str(self.name) + ' ' + str(self.university)

def foobar():
    data = bytearray()
    inp = zpp_serializer.MemoryInputArchive(data)
    out = zpp_serializer.MemoryOutputArchive(data)

    out(Point(x=1337, y=1338))

    my_point = Point()
    inp(my_point)

    print "%s %s" % (my_point.x, my_point.y)

def foo():
    data = bytearray()
    inp = zpp_serializer.MemoryInputArchive(data)
    out = zpp_serializer.MemoryOutputArchive(data)

    my_person = Student(name="1337", university="1337University")
    out(my_person)

    other_person = inp(Person)
    other_person.print_me()

def main():
    foobar()
    foo()

if __name__ == '__main__':
    sys.exit(main())

```

Another example:
```py
import zpp_serializer
import sys

@zpp_serializer.polymorphic('v1::a')
class A(object):
    i = zpp_serializer.Uint64
    j = zpp_serializer.Uint32
    k = zpp_serializer.Uint8

@zpp_serializer.polymorphic('v1::b')
class B(A):
    l = zpp_serializer.Uint8
    v = zpp_serializer.Vector(zpp_serializer.Uint16)
    a = zpp_serializer.Array(zpp_serializer.Uint16, 4)

@zpp_serializer.polymorphic('v1::c')
class C(B):
    m = zpp_serializer.Uint32
    s = zpp_serializer.String
    w = zpp_serializer.WString

def main():
    c = C(i=0x1337, j=0x1338, k=1, l=3, m=7)
    c.v = [1, 2, 3]
    c.a[1:3] = [5, 6]
    c.s = "hello world"
    c.w = u"hello world"
    data = bytearray()
    out = zpp_serializer.MemoryOutputArchive(data)
    inp = zpp_serializer.MemoryInputArchive(data)
    out(c)
    a = inp(A)
    print c
    print a

if __name__ == '__main__':
    sys.exit(main())

```

