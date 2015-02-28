"""
:mod:`asyncio_xmpp.stanza_model` --- Declarative-style stanza definition
########################################################################

This module provides facilities to create classes which map to full XMPP stanzas
(including payload).

To create such a class, derive from :class:`StanzaObject` and provide attributes
using the :class:`Attr`, :class:`Text`, :class:`Child` and :class:`ChildList`
descriptors.

Terminology
===========

A word on tags
--------------

Tags, as used by etree, are used throughout this module. Note that we are
representing tags as tuples of ``(namespace_uri, localname)``, where
``namespace_uri`` may be :data:`None`.

.. seealso::

   The functions :func:`normalize_tag` and :func:`tag_to_str` are useful to
   convert from and to ElementTree compatible strings.


Suspendable functions
---------------------

This module uses suspendable functions, implemented as generators, at several
points. These may also be called coroutines, but have nothing to do with
coroutines as used by :mod:`asyncio`, which is why we will call them suspendable
functions here.

Suspendable functions possibly take arguments and then operate on input which is
fed to them in a push-manner step by step (using the
:meth:`~types.GeneratorType.send` method). The main usage in this module is to
process SAX events: The SAX events are processed step-by-step by the functions,
and when the event is fully processed, it suspends itself (using ``yield``)
until the next event is sent into it.

Descriptors for XML-sourced attributes
======================================

The following descriptors can be used to load attributes from stanza XML. There
are two fundamentally different descriptor types: *scalar* and *non-scalar*
(e.g. list) descriptors. *scalar* descriptor types always accept a value of
:data:`None`, which represents the *absence* of the object (unless it is
required by some means, e.g. ``Attr(required=True)``). *Non-scalar* descriptors
generally have a different way to describe the absence and in addition have a
mutable value. Assignment to the descriptor attribute is strictly type-checked.

Scalar descriptors
------------------

.. autoclass:: Attr(name, type_=stanza_types.String(), default=None, required=False, validator=None, validate=ValidateMode.FROM_RECV)

.. autoclass:: Child(classes, default=None)

.. autoclass:: ChildText(tag, child_policy=UnknownChildPolicy.FAIL, attr_policy=UnknownAttrPolicy.FAIL, type_=stanza_types.String(), default=None, validator=None, validate=ValidateMode.FROM_RECV)

.. autoclass:: Text(type_=stanza_types.String(), default=None, validator=None, validate=ValidateMode.FROM_RECV)

Non-scalar descriptors
----------------------

.. autoclass:: ChildList(classes)

.. autoclass:: Collector()


Parsing stanzas
===============

To parse stanzas, an asynchronous approach which uses SAX-like events is
followed. For this, the suspendable functions explained earlier are used. The
main function to parse a stanza from events is :func:`stanza_parser`. To drive
that suspendable function from SAX events, use a :class:`SAXDriver`.

.. autofunction:: stanza_parser

.. autoclass:: SAXDriver

Base and meta class
===================

The :class:`StanzaObject` base class makes use of the :class:`StanzaClass`
metaclass and provides implementations for utility methods. For an object to
work with this module, it must derive from :class:`StanzaObject` or provide an
identical interface.

.. autoclass:: StanzaObject()

The metaclass takes care of collecting the special descriptors in attributes
where they can be used by the SAX event interpreter to fill the class with
data. It also provides a class method for late registration of child classes.

.. autoclass:: StanzaClass

Functions, enumerations and exceptions
======================================

.. autofunction:: normalize_tag

.. autofunction:: tag_to_str

The values of the following enumerations are used on "magic" attributes of
:class:`StanzaClass` instances (i.e. classes).

.. autoclass:: UnknownChildPolicy

.. autoclass:: UnknownAttrPolicy

.. autoclass:: ValidateMode

The following exceptions are generated at some places in this module:

.. autoclass:: UnknownTopLevelTag

"""
import copy
import inspect
import sys
import xml.sax.handler

from enum import Enum

from asyncio_xmpp.utils import etree

from . import stanza_types


def tag_to_str(tag):
    """
    *tag* must be a tuple ``(namespace_uri, localname)``. Return a tag string
    conforming to the ElementTree specification. Example::

         tag_to_str(("jabber:client", "iq")) == "{jabber:client}iq"
    """
    return "{{{:s}}}{:s}".format(*tag) if tag[0] else tag[1]


def normalize_tag(tag):
    """
    Normalize an XML element tree *tag* into the tuple format. The following
    input formats are accepted:

    * ElementTree namespaced string, e.g. ``{uri:bar}foo``
    * Unnamespaced tags, e.g. ``foo``
    * Two-tuples consisting of *namespace_uri* and *localpart*; *namespace_uri*
      may be :data:`None` if the tag is supposed to be namespaceless. Otherwise
      it must be, like *localpart*, a :class:`str`.

    Return a two-tuple consisting the ``(namespace_uri, localpart)`` format.
    """
    if isinstance(tag, str):
        namespace_uri, sep, localname = tag.partition("}")
        if sep:
            if not namespace_uri.startswith("{"):
                raise ValueError("not a valid etree-format tag")
            namespace_uri = namespace_uri[1:]
        else:
            localname = namespace_uri
            namespace_uri = None
        return (namespace_uri, localname)
    elif len(tag) != 2:
        raise ValueError("not a valid tuple-format tag")
    else:
        if any(part is not None and not isinstance(part, str) for part in tag):
            raise TypeError("tuple-format tags must only contain str and None")
        if tag[1] is None:
            raise ValueError("tuple-format localname must not be None")
    return tag


class UnknownChildPolicy(Enum):
    """
    Describe the event which shall take place whenever a child element is
    encountered for which no descriptor can be found to parse it.

    .. attribute:: FAIL

       Raise a :class:`ValueError`

    .. attribute:: DROP

       Drop and ignore the element and all of its children

    """

    FAIL = 0
    DROP = 1


class UnknownAttrPolicy(Enum):
    """
    Describe the event which shall take place whenever a XML attribute is
    encountered for which no descriptor can be found to parse it.

    .. attribute:: FAIL

       Raise a :class:`ValueError`

    .. attribute:: DROP

       Drop and ignore the attribute

    """
    FAIL = 0
    DROP = 1


class ValidateMode(Enum):
    """
    Control which ways to set a value in a descriptor are passed through a
    validator.

    .. attribute:: FROM_RECV

       Values which are obtained from XML source are validated.

    .. attribute:: FROM_CODE

       Values which are set through attribute access are validated.

    .. attribute:: ALWAYS

       All values, whether set by attribute or obtained from XML source, are
       validated.

    """

    FROM_RECV = 1
    FROM_CODE = 2
    ALWAYS = 3

    @property
    def from_recv(self):
        return self.value & 1

    @property
    def from_code(self):
        return self.value & 2

class UnknownTopLevelTag(ValueError):
    """
    Subclass of :class:`ValueError`. *ev_args* must be the arguments of the
    ``"start"`` event and are stored as the :attr:`ev_args` attribute for
    inspection.

    .. attribute:: ev_args

       The *ev_args* passed to the constructor.

    """

    def __init__(self, msg, ev_args):
        super().__init__(msg + ": {}".format((ev_args[0], ev_args[1])))
        self.ev_args = ev_args


class _PropBase:
    def __init__(self, default,
                 validator=None,
                 validate=ValidateMode.FROM_RECV):
        super().__init__()
        self._default = default
        self.validate = validate
        self.validator = validator

    def _set(self, instance, value):
        instance._stanza_props[self] = value

    def __set__(self, instance, value):
        if     (self.validate.from_code and
                self.validator and
                not self.validator.validate(value)):
            raise ValueError("invalid value")
        self._set(instance, value)

    def _set_from_code(self, instance, value):
        self.__set__(instance, value)

    def _set_from_recv(self, instance, value):
        if     (self.validate.from_recv and
                self.validator and
                not self.validator.validate(value)):
            raise ValueError("invalid value")
        self._set(instance, value)

    def __get__(self, instance, cls):
        if instance is None:
            return self
        try:
            return instance._stanza_props[self]
        except KeyError as err:
            return self._default


class Text(_PropBase):
    """
    When assigned to a class’ attribute, it collects all character data of the
    XML element.

    Note that this destroys the relative ordering of child elements and
    character data pieces. This is known and a WONTFIX, as it is not required in
    XMPP to keep that relative order: Elements either have character data *or*
    other elements as children.

    The *type_*, *validator*, *validate* and *default* arguments behave like in
    :class:`Attr`.

    .. automethod:: from_value

    .. automethod:: to_node
    """

    def __init__(self,
                 type_=stanza_types.String(),
                 default=None,
                 **kwargs):
        super().__init__(default, **kwargs)
        self.type_ = type_

    def from_value(self, instance, value):
        """
        Convert the given value using the set *type_* and store it into
        *instance*’ attribute.
        """
        self._set_from_recv(instance, self.type_.parse(value))

    def to_node(self, instance, el):
        """
        Assign the formatted value stored at *instance*’ attribute to the text
        of *el*.

        If the *value* is :data:`None`, no text is generated.
        """
        value = self.__get__(instance, type(instance))
        if value is None:
            return
        el.text = self.type_.format(value)


class Child(_PropBase):
    """
    When assigned to a class’ attribute, it collects any child which matches any
    :attr:`StanzaObject.TAG` of the given *classes*.

    The tags among the *classes* must be unique, otherwise :class:`ValueError`
    is raised on construction.

    The *default* argument behaves like in :class:`Attr`. Validators are not
    supported.

    .. automethod:: get_tag_map

    .. automethod:: from_events

    .. automethod:: to_node
    """

    def __init__(self, classes, default=None):
        super().__init__(default)
        self._classes = tuple(classes)
        self._tag_map = {}
        for cls in self._classes:
            self._register(cls)

    def get_tag_map(self):
        """
        Return a dictionary mapping the tags of the supported classes to the
        classes themselves. Can be used to obtain a set of supported tags.
        """
        return self._tag_map

    def _process(self, instance, ev_args):
        cls = self._tag_map[ev_args[0], ev_args[1]]
        return (yield from cls.parse_events(ev_args))

    def from_events(self, instance, ev_args):
        """
        Detect the object to instanciate from the arguments *ev_args* of the
        ``"start"`` event. The new object is stored at the corresponding
        descriptor attribute on *instance*.

        This method is suspendable.
        """
        obj = yield from self._process(instance, ev_args)
        self.__set__(instance, obj)
        return obj

    def to_node(self, instance, parent):
        """
        Take the object associated with this descriptor on *instance* and
        serialize it as child into the given :class:`lxml.etree.Element`
        *parent*.

        If the object is :data:`None`, no content is generated.
        """
        obj = self.__get__(instance, type(instance))
        if obj is None:
            return
        obj.unparse_to_node(parent)

    def _register(self, cls):
        if cls.TAG in self._tag_map:
            raise ValueError("ambiguous children: {} and {} share the same "
                             "TAG".format(
                                 self._tag_map[cls.TAG],
                                 cls))
        self._tag_map[cls.TAG] = cls


class ChildList(Child):
    """
    The :class:`ChildList` works like :class:`Child`, with two key differences:

    * multiple children which are matched by this descriptor get collected into
      a list
    * the default is fixed at an empty list.

    .. automethod:: from_events

    .. automethod:: to_node
    """

    def __init__(self, classes):
        super().__init__(classes)

    def __get__(self, instance, cls):
        if instance is None:
            return super().__get__(instance, cls)
        return instance._stanza_props.setdefault(self, [])

    def from_events(self, instance, ev_args):
        """
        Like :meth:`.Child.from_events`, but instead of replacing the attribute
        value, the new object is appended to the list.
        """

        obj = yield from self._process(instance, ev_args)
        self.__get__(instance, type(instance)).append(obj)
        return obj

    def to_node(self, instance, parent):
        """
        Like :meth:`.Child.to_node`, but instead of serializing a single object,
        all objects in the list are serialized.
        """

        for item in self.__get__(instance, type(instance)):
            item.unparse_to_node(parent)


class Collector(_PropBase):
    """
    When assigned to a class’ attribute, it collects all children which are not
    known to any other descriptor into a list of XML subtrees.

    The default is fixed at an empty list.

    .. automethod:: from_events

    .. automethod:: to_node
    """

    def __init__(self):
        super().__init__(default=[])

    def __get__(self, instance, cls):
        if instance is None:
            return super().__get__(instance, cls)
        return instance._stanza_props.setdefault(self, [])

    def from_events(self, instance, ev_args):
        """
        Collect the events and convert them to a single XML subtree, which then
        gets appended to the list at *instance*. *ev_args* must be the arguments
        of the ``"start"`` event of the new child.

        This method is suspendable.
        """

        def make_from_args(ev_args, parent):
            if parent is not None:
                el = etree.SubElement(parent,
                                      tag_to_str((ev_args[0], ev_args[1])))
            else:
                el = etree.Element(tag_to_str((ev_args[0], ev_args[1])))
            for key, value in ev_args[2].items():
                el.set(tag_to_str(key), value)
            return el

        root_el = make_from_args(ev_args, None)
        stack = [root_el]
        while stack:
            ev_type, *ev_args = yield
            if ev_type == "start":
                stack.append(make_from_args(ev_args, stack[-1]))
            elif ev_type == "text":
                curr = stack[-1]
                if curr.text is not None:
                    curr.text += ev_args[0]
                else:
                    curr.text = ev_args[0]
            elif ev_type == "end":
                stack.pop()
            else:
                raise ValueError(ev_type)

        self.__get__(instance, type(instance)).append(root_el)

    def to_node(self, instance, parent):
        """
        Add all XML subtrees on *instance* to the *parent* node.
        """
        for node in self.__get__(instance, type(instance)):
            parent.append(copy.copy(node))


class Attr(Text):
    """
    When assigned to a class’ attribute, it binds that attribute to the XML
    attribute with the given *tag*. *tag* must be a valid input to
    :func:`normalize_tag`.

    The following arguments occur at several of the descriptor classes, and are
    all available at :class:`Attr`.

    :param type_: An object which fulfills the type interface proposed by
                  :mod:`~asyncio_xmpp.stanza_types`. Usually, this is defaulted
                  to a :class:`~asyncio_xmpp.stanza_types.String` instance.
    :param validator: An object which has a :meth:`validate` method. That method
                      receives a value which was either assigned to the property
                      (depending on the *validate* argument) or parsed from XML
                      (after it passed through *type_*).
    :param validate: A value from the :class:`ValidateMode` enum, which defines
                     which values have to pass through the validator. At some
                     points it makes sense to only validate outgoing values, but
                     be liberal with incoming values. This defaults to
                     :attr:`ValidateMode.FROM_RECV`.
    :param default: The value which the attribute has if no value has been
                    assigned. This defaults to :data:`None`.
    :param required: Whether the absence of data for this object during parsing
                     is a fatal error. This defaults to :data:`False`.

    .. automethod:: from_value

    .. automethod:: to_node

    """

    def __init__(self, tag,
                 type_=stanza_types.String(),
                 default=None,
                 required=False,
                 **kwargs):
        super().__init__(type_=type_, default=default, **kwargs)
        self.tag = normalize_tag(tag)
        self.required = required

    def to_node(self, instance, parent):
        """
        Override the implementation from :class:`Text` by storing the formatted
        value in the XML attribute instead of the character data.

        If the value is :data:`None`, no element is generated.
        """
        value = self.__get__(instance, type(instance))
        if value is None:
            return

        parent.set(tag_to_str(self.tag), self.type_.format(value))


class ChildText(_PropBase):
    """
    When assigned to a class’ attribute, it binds that attribute to the XML
    character data of a child element with the given *tag*. *tag* must be a
    valid input to :func:`normalize_tag`.

    The *type_*, *validate*, *validator* and *default* arguments behave like in
    :class:`Attr`.

    *child_policy* is applied when :meth:`from_events` encounters an element in
    the child element of which it is supposed to extract text. Likewise,
    *attr_policy* is applied if an attribute is encountered on the element.

    .. automethod:: get_tag_map

    .. automethod:: from_events

    .. automethod:: to_node

    """

    def __init__(self, tag,
                 type_=stanza_types.String(),
                 default=None,
                 child_policy=UnknownChildPolicy.FAIL,
                 attr_policy=UnknownAttrPolicy.FAIL,
                 **kwargs):
        super().__init__(default=default, **kwargs)
        self.tag = normalize_tag(tag)
        self.type_ = type_
        self.default = default
        self.child_policy = child_policy
        self.attr_policy = attr_policy

    def get_tag_map(self):
        """
        Return an iterable yielding :attr:`tag`.

        This is for compatiblity with the :class:`Child` interface.
        """
        return {self.tag}

    def from_events(self, instance, ev_args):
        """
        Starting with the element to which the start event information in
        *ev_args* belongs, parse text data. If any children are encountered,
        :attr:`child_policy` is enforced (see
        :class:`UnknownChildPolicy`). Likewise, if the start event contains
        attributes, :attr:`attr_policy` is enforced
        (c.f. :class:`UnknownAttrPolicy`).

        The extracted text is passed through :attr:`type_` and :attr:`validator`
        and if it passes, stored in the attribute on the *instance* with which
        the property is associated.

        This method is suspendable.
        """
        attrs = ev_args[2]
        if attrs and self.attr_policy == UnknownAttrPolicy.FAIL:
            raise ValueError("unexpected attribute (at text only node)")
        parts = []
        while True:
            ev_type, *ev_args = yield
            if ev_type == "text":
                parts.append(ev_args[0])
            elif ev_type == "start":
                if self.child_policy == UnknownChildPolicy.FAIL:
                    raise ValueError("unexpected child (in text only node)")
                else:
                    yield from drop_handler(ev_args)
            elif ev_type == "end":
                break
        self._set_from_recv(instance, self.type_.parse("".join(parts)))

    def to_node(self, instance, parent):
        """
        Create a child node at *parent* with the tag :attr:`tag`. Set the text
        contents to the value of the attribute which this descriptor represents
        at *instance*.

        If the value is :data:`None`, no element is generated.
        """
        value = self.__get__(instance, type(instance))
        if value is None:
            return
        el = etree.SubElement(parent, tag_to_str(self.tag))
        el.text = self.type_.format(value)
        return el


class StanzaClass(type):
    """
    There should be no need to use this metaclass directly when implementing
    your own stanza classes. Instead, derive from :class:`StanzaObject`.

    The following restrictions apply when a class uses the :class:`StanzaClass`
    metaclass:

    1. At no point in the inheritance tree there must exist more than one
       distinct :class:`Text` descriptor. It is possible to inherit two
       identical text descriptors from several base classes though.

    2. The above applies equivalently for :class:`Collector` descriptors.

    3. At no point in the inheritance tree there must exist more than one
       :class:`Attr` descriptor which handles a given attribute tag. Like with
       :class:`Text`, it is allowed that the same :class:`Attr` descriptor is
       inherited through multiple paths from parent classes.

    4. The above applies likewise for element tags and :class:`Child` (or
       :class:`ChildList`) descriptors.

    Objects of this metaclass (i.e. classes) have some useful attributes. The
    following attributes are gathered from the namespace of the class, by
    collecting the different stanza-related descriptors:

    .. attribute:: TEXT_PROPERTY

       The :class:`Text` descriptor object associated with this class. This is
       :data:`None` if no attribute using that descriptor is declared on the
       class.

    .. attribute:: COLLECTOR_PROPERTY

       The :class:`Collector` descriptor object associated with this class. This
       is :data:`None` if no attribute using that descriptor is declared on the
       class.

    .. attribute:: ATTR_MAP

       A dictionary mapping attribute tags to the :class:`Attr` descriptor
       objects for these attributes.

    .. attribute:: CHILD_MAP

       A dictionary mapping element tags to the :class:`Child` (or
       :class:`ChildList`) descriptor objects which accept these child
       elements.

    .. attribute:: CHILD_PROPS

       A (frozen) set of all :class:`Child` (or :class:`ChildList`) descriptor
       objects of this class.

    .. note::

       :class:`StanzaObject` defines defaults for more attributes which also
       must be present on objects which are used as stanza objects.

    When inheriting from :class:`StanzaClass` objects, the properties are merged
    sensibly.

    """

    def __new__(mcls, name, bases, namespace):
        text_property = None
        child_map = {}
        child_props = set()
        attr_map = {}
        collector_property = None

        for base in reversed(bases):
            if not isinstance(base, StanzaClass):
                continue

            if base.TEXT_PROPERTY is not None:
                if     (text_property is not None and
                        base.TEXT_PROPERTY is not text_property):
                    raise TypeError("multiple text properties in inheritance")
                text_property = base.TEXT_PROPERTY

            for key, prop in base.CHILD_MAP.items():
                try:
                    existing = child_map[key]
                except KeyError:
                    child_map[key] = prop
                else:
                    if existing is not prop:
                        raise TypeError("ambiguous Child properties inherited")

            child_props |= base.CHILD_PROPS

            for key, prop in base.ATTR_MAP.items():
                try:
                    existing = attr_map[key]
                except KeyError:
                    attr_map[key] = prop
                else:
                    if existing is not prop:
                        raise TypeError("ambiguous Attr properties inherited")

            if base.COLLECTOR_PROPERTY is not None:
                if     (collector_property is not None and
                        base.COLLECTOR_PROPERTY is not collector_property):
                    raise TypeError("multiple collector properties in "
                                    "inheritance")
                collector_property = base.COLLECTOR_PROPERTY

        for attrname, obj in namespace.items():
            if isinstance(obj, Attr):
                if obj.tag in attr_map:
                    raise TypeError("ambiguous Attr properties")
                attr_map[obj.tag] = obj
            elif isinstance(obj, Text):
                if text_property is not None:
                    raise TypeError("multiple Text properties on stanza class")
                text_property = obj
            elif isinstance(obj, (Child, ChildText)):
                for key in obj.get_tag_map():
                    if key in child_map:
                        raise TypeError("ambiguous Child properties: {} and {}"
                                        " both use the same tag".format(
                                            child_map[key],
                                            obj))
                    child_map[key] = obj
                child_props.add(obj)
            elif isinstance(obj, Collector):
                if collector_property is not None:
                    raise TypeError("multiple Collector properties on stanza "
                                    "class")
                collector_property = obj

        namespace["TEXT_PROPERTY"] = text_property
        namespace["CHILD_MAP"] = child_map
        namespace["CHILD_PROPS"] = frozenset(child_props)
        namespace["ATTR_MAP"] = attr_map
        namespace["COLLECTOR_PROPERTY"] = collector_property

        try:
            tag = namespace["TAG"]
        except KeyError:
            pass
        else:
            try:
                namespace["TAG"] = normalize_tag(tag)
            except ValueError:
                raise TypeError("TAG attribute has incorrect format")

        return super().__new__(mcls, name, bases, namespace)

    def parse_events(cls, ev_args):
        """
        Create an instance of this class, using the events sent into this
        function. *ev_args* must be the event arguments of the ``"start"``
        event.

        .. seealso::

           You probably should not call this method directly, but instead use
           :func:`stanza_parser` with a :class:`SAXDriver`.

        This method is suspendable.
        """
        obj = cls()
        attrs = ev_args[2]
        attr_map = cls.ATTR_MAP.copy()
        for key, value in attrs.items():
            try:
                prop = attr_map.pop(key)
            except KeyError:
                if cls.UNKNOWN_ATTR_POLICY == UnknownAttrPolicy.DROP:
                    continue
                else:
                    raise ValueError("unexpected attribute {!r} on {}".format(
                        key,
                        tag_to_str((ev_args[0], ev_args[1]))
                    )) from None
            prop.from_value(obj, value)

        for key, prop in attr_map.items():
            if prop.required:
                raise ValueError("missing attribute {!r} on {}".format(
                    key,
                    tag_to_str((ev_args[0], ev_args[1]))
                ))

        collected_text = []
        while True:
            ev_type, *ev_args = yield
            if ev_type == "end":
                break
            elif ev_type == "text":
                collected_text.append(ev_args[0])
            elif ev_type == "start":
                try:
                    handler = cls.CHILD_MAP[ev_args[0], ev_args[1]]
                except KeyError:
                    if cls.COLLECTOR_PROPERTY:
                        handler = cls.COLLECTOR_PROPERTY
                    elif cls.UNKNOWN_CHILD_POLICY == UnknownChildPolicy.DROP:
                        yield from drop_handler(ev_args)
                        continue
                    else:
                        raise ValueError("unexpected child TAG: {}".format(
                            (ev_args[0], ev_args[1]))) from None
                yield from handler.from_events(obj, ev_args)

        if collected_text:
            if cls.TEXT_PROPERTY:
                cls.TEXT_PROPERTY.from_value(obj, "".join(collected_text))
            else:
                raise ValueError("unexpected text")

        return obj

    def register_child(cls, prop, child_cls):
        """
        Register a new :class:`StanzaClass` instance *child_cls* for a given
        :class:`Child` descriptor *prop*.

        .. warning::

           For now, this only modifies the :attr:`CHILD_MAP` of this class, not
           of any subclasses. Thus, subclasses will *not* pick up this change,
           unless they are *declared* after the change has been made.

           This may be subject to change in the future, which will also come
           with a change in the inheritance rules to make them consistent.

        """
        if child_cls.TAG in cls.CHILD_MAP:
            raise ValueError("ambiguous Child")

        prop._register(child_cls)
        cls.CHILD_MAP[child_cls.TAG] = prop


class StanzaObject(metaclass=StanzaClass):
    """
    Represent an object which may be converted to a stanza (or part of a
    stanza). These objects can also be created and validated on-the-fly from
    SAX-like events using :func:`stanza_parser`. The constructor does not
    require any arguments and forwards them directly the next class in the
    resolution order.

    To declare a stanza object, inherit from :class:`StanzaObject` and provide
    the following attributes on your class:

    * A ``TAG`` attribute, which is a tuple ``(namespace_uri, localname)``
      representing the tag of the XML element you want to match.
    * An arbitrary number of :class:`Text`, :class:`Collector`, :class:`Child`,
      :class:`ChildList` and :class:`Attr`-based attributes.

    To further influence the parsing behaviour of a class, two attributes are
    provided which give policies for unexpected elements in the XML tree:

    .. attribute:: UNKNOWN_CHILD_POLICY = UnknownChildPolicy.FAIL

       A value from the :class:`UnknownChildPolicy` enum which defines the
       behaviour if a child is encountered for which no matching attribute is
       found.

       Note that this policy has no effect if a :class:`Collector` descriptor is
       present, as it takes all children for which no other descriptor exists,
       thus all children are known.

    .. attribute:: UNKNOWN_ATTR_POLICY = UnknownAttrPolicy.FAIL

       A value from the :class:`UnknownAttrPolicy` enum which defines the
       behaviour if an attribute is encountered for which no matching descriptor
       is found.

    Example::

        class Body(stanza_model.StanzaObject):
            TAG = ("jabber:client", "body")

            text = stanza_model.Text()

        class Message(stanza_model.StanzaObject):
            TAG = ("jabber:client", "message")
            UNKNOWN_CHILD_POLICY = stanza_model.UnknownChildPolicy.DROP

            type_ = stanza_model.Attr(tag="type", required=True)
            from_ = stanza_model.Attr(tag="from", required=True)
            to = stanza_model.Attr(tag="to")
            id_ = stanza_model.Attr(tag="id")

            body = stanza_model.Child([Body])


    To add a stanza object to an :class:`lxml.etree.Element`, use
    :meth:`unparse_to_node`.

    The following methods are available on instances of :class:`StanzaObject`:

    .. automethod:: unparse_to_node

    The following **class methods** are provided by the metaclass:

    .. automethod:: parse_events(ev_args)

    .. automethod:: register_child(prop, child_cls)

    """
    UNKNOWN_CHILD_POLICY = UnknownChildPolicy.FAIL
    UNKNOWN_ATTR_POLICY = UnknownAttrPolicy.FAIL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stanza_props = dict()

    def unparse_to_node(self, parent):
        cls = type(self)
        el = etree.SubElement(
            parent,
            tag_to_str(self.TAG)
        )
        for prop in cls.ATTR_MAP.values():
            prop.to_node(self, el)
        if cls.TEXT_PROPERTY:
            cls.TEXT_PROPERTY.to_node(self, el)
        for prop in cls.CHILD_PROPS:
            prop.to_node(self, el)
        return el


class SAXDriver(xml.sax.handler.ContentHandler):
    """
    This is a :class:`xml.sax.handler.ContentHandler` subclass which *only*
    supports namespace-conforming SAX event sources.

    *dest_generator_factory* must be a function which returns a new suspendable
    method supporting the interface of :func:`stanza_parser`. The SAX events are
    converted to an internal event format and sent to the suspendable function
    in order.

    *on_emit* may be a callable. Whenever a suspendable function returned by
    *dest_generator_factory* returns, with the return value as sole argument.

    When you are done with a :class:`SAXDriver`, you should call :meth:`close`
    to clean up internal parser state.

    .. automethod:: close
    """

    def __init__(self, dest_generator_factory, on_emit=None):
        self._on_emit = on_emit
        self._dest_factory = dest_generator_factory
        self._dest = None

    def _emit(self, value):
        if self._on_emit:
            self._on_emit(value)

    def _send(self, value):
        if self._dest is None:
            self._dest = self._dest_factory()
            self._dest.send(None)
        try:
            self._dest.send(value)
        except StopIteration as err:
            self._emit(err.value)
            self._dest = None

    def startElementNS(self, name, qname, attributes):
        uri, localname = name
        self._send(("start", uri, localname, dict(attributes)))

    def characters(self, data):
        self._send(("text", data))

    def endElementNS(self, name, qname):
        self._send(("end",))

    def close(self):
        """
        Clean up all internal state.
        """
        if self._dest is not None:
            self._dest.close()
            self._dest = None


def stanza_parser(stanza_classes):
    """
    Parse one of the stanza classes provided, depending on what tag the start
    element has. If the start element tag is not equal to any of the stanza
    classes tags, :class:`UnknownTopLevelTag` is raised.

    When the parsing terminates, the fully instanciated object is returned.

    Example::

         # let Message be a StanzaObject class, like in the StanzaObject example

         result = None
         def catch_result(value):
             nonlocal result
             result = value

         sd = stanza_model.SAXDriver(
             functools.partial(stanza_parser, [Message]),
             on_emit=catch_result
         )
         lxml.sax.saxify(lxml.etree.fromstring(
              "<message id='foo' from='bar' type='chat' />")
         )

         # result is now a Message instance, having the attributes filled in
         # accordingly

    This function is suspendable.
    """
    ev_type, *ev_args = yield
    for cls in stanza_classes:
        if cls.TAG == (ev_args[0], ev_args[1]):
            cls_to_use = cls
            break
    else:
        raise UnknownTopLevelTag(
            "unhandled top-level element",
            ev_args)

    generator = cls_to_use.parse_events(ev_args)
    return (yield from generator)


def drop_handler(ev_args):
    depth = 1
    while depth:
        ev = yield
        if ev[0] == "start":
            depth += 1
        elif ev[0] == "end":
            depth -= 1
