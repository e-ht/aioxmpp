import copy
import functools
import unittest
import unittest.mock

import lxml.sax

import asyncio_xmpp.stanza_model as stanza_model
import asyncio_xmpp.stanza_types as stanza_types

from asyncio_xmpp.utils import etree

from .xmltestutils import XMLTestCase


def from_wrapper(fun, *args):
    ev_type, *ev_args = yield
    return (yield from fun(*args+(ev_args,)))


def drive_from_events(method, instance, subtree):
    sd = stanza_model.SAXDriver(
        functools.partial(from_wrapper, method, instance)
    )
    lxml.sax.saxify(subtree, sd)


def make_instance_mock(mapping={}):
    instance = unittest.mock.MagicMock()
    instance._stanza_props = dict(mapping)
    return instance


class Testtag_to_str(unittest.TestCase):
    def test_unqualified(self):
        self.assertEqual(
            "foo",
            stanza_model.tag_to_str((None, "foo"))
        )

    def test_with_namespace(self):
        self.assertEqual(
            "{uri:bar}foo",
            stanza_model.tag_to_str(("uri:bar", "foo"))
        )


class Testnormalize_tag(unittest.TestCase):
    def test_unqualified(self):
        self.assertEqual(
            (None, "foo"),
            stanza_model.normalize_tag("foo")
        )

    def test_with_namespace(self):
        self.assertEqual(
            ("uri:bar", "foo"),
            stanza_model.normalize_tag(("uri:bar", "foo"))
        )

    def test_etree_format(self):
        self.assertEqual(
            ("uri:bar", "foo"),
            stanza_model.normalize_tag("{uri:bar}foo")
        )

    def test_validate_etree_format(self):
        with self.assertRaises(ValueError):
            stanza_model.normalize_tag("uri:bar}foo")

    def test_validate_tuple_format(self):
        with self.assertRaises(ValueError):
            stanza_model.normalize_tag(("foo",))
        with self.assertRaises(ValueError):
            stanza_model.normalize_tag(("foo", "bar", "baz"))
        with self.assertRaises(ValueError):
            stanza_model.normalize_tag(("foo", None))
        with self.assertRaises(ValueError):
            stanza_model.normalize_tag((None, None))

    def test_reject_incorrect_types(self):
        with self.assertRaises(TypeError):
            stanza_model.normalize_tag(1)
        with self.assertRaises(TypeError):
            stanza_model.normalize_tag((1, 2))


class TestStanzaClass(unittest.TestCase):
    def test_init(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = None, "foo"

        self.assertIsNone(Cls.TEXT_PROPERTY)
        self.assertIsNone(Cls.COLLECTOR_PROPERTY)
        self.assertFalse(Cls.CHILD_MAP)
        self.assertFalse(Cls.CHILD_PROPS)
        self.assertFalse(Cls.ATTR_MAP)

    def test_forbid_malformed_tag(self):
        with self.assertRaisesRegexp(TypeError,
                                     "TAG attribute has incorrect format"):
            class Cls(metaclass=stanza_model.StanzaClass):
                TAG = "foo", "bar", "baz"

        with self.assertRaisesRegexp(TypeError,
                                     "TAG attribute has incorrect format"):
            class Cls(metaclass=stanza_model.StanzaClass):
                TAG = "foo",

    def test_normalize_tag(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
        self.assertEqual(
            (None, "foo"),
            Cls.TAG)

    def test_collect_text_property(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
            prop = stanza_model.Text()

        self.assertIs(
            Cls.prop,
            Cls.TEXT_PROPERTY)

    def test_inheritance_text_one_level(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            text = stanza_model.Text()

        with self.assertRaises(TypeError):
            class ClsB(ClsA):
                text2 = stanza_model.Text()

        class ClsB(ClsA):
            pass

        self.assertIs(
            ClsA.text,
            ClsB.TEXT_PROPERTY)

    def test_multi_inheritance_text(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            text = stanza_model.Text()

        class ClsB(metaclass=stanza_model.StanzaClass):
            text2 = stanza_model.Text()

        with self.assertRaises(TypeError):
            class ClsC(ClsA, ClsB):
                pass

    def test_diamond_inheritance_text(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            text = stanza_model.Text()

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertIs(
            ClsA.text,
            ClsD.TEXT_PROPERTY)

    def test_collect_child_text_property(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            body = stanza_model.ChildText("body")

        self.assertDictEqual(
            {
                (None, "body"): ClsA.body,
            },
            ClsA.CHILD_MAP)
        self.assertSetEqual(
            {ClsA.body},
            ClsA.CHILD_PROPS)

    def test_collect_child_property(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
        class ClsB(metaclass=stanza_model.StanzaClass):
            TAG = "bar"
        class ClsC(metaclass=stanza_model.StanzaClass):
            TAG = "baz"

        class Cls(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.Child([ClsA, ClsB])
            c2 = stanza_model.Child([ClsC])

        self.assertDictEqual(
            {
                ClsA.TAG: Cls.c1,
                ClsB.TAG: Cls.c1,
                ClsC.TAG: Cls.c2,
            },
            Cls.CHILD_MAP)
        self.assertSetEqual(
            {Cls.c1, Cls.c2},
            Cls.CHILD_PROPS)

    def test_forbid_ambiguous_children(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
        class ClsB(metaclass=stanza_model.StanzaClass):
            TAG = "foo"

        with self.assertRaisesRegexp(TypeError, "ambiguous Child properties"):
            class Cls(metaclass=stanza_model.StanzaClass):
                c1 = stanza_model.Child([ClsA])
                c2 = stanza_model.Child([ClsB])

    def test_inheritance_child(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsLeafB:
            TAG = "bar"

        class ClsA(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.Child([ClsLeafA])

        class ClsB(ClsA):
            c2 = stanza_model.Child([ClsLeafB])

        self.assertDictEqual(
            {
                "foo": ClsA.c1,
                "bar": ClsB.c2,
            },
            ClsB.CHILD_MAP)
        self.assertSetEqual(
            {ClsA.c1, ClsB.c2},
            ClsB.CHILD_PROPS)

    def test_inheritance_child_ambiguous(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsA(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.Child([ClsLeafA])

        with self.assertRaisesRegexp(TypeError, "ambiguous Child properties"):
            class ClsB(ClsA):
                c2 = stanza_model.Child([ClsLeafA])

    def test_multi_inheritance_child(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsLeafB:
            TAG = "bar"

        class ClsA(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.Child([ClsLeafA])

        class ClsB(metaclass=stanza_model.StanzaClass):
            c2 = stanza_model.Child([ClsLeafB])

        class ClsC(ClsA, ClsB):
            pass

        self.assertDictEqual(
            {
                "foo": ClsA.c1,
                "bar": ClsB.c2,
            },
            ClsC.CHILD_MAP)
        self.assertSetEqual(
            {ClsA.c1, ClsB.c2},
            ClsC.CHILD_PROPS)

    def test_multi_inheritance_child_ambiguous(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsA(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.Child([ClsLeafA])

        class ClsB(metaclass=stanza_model.StanzaClass):
            c2 = stanza_model.Child([ClsLeafA])

        with self.assertRaises(TypeError):
            class ClsC(ClsB, ClsA):
                pass

    def test_diamond_inheritance_child(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsA(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.Child([ClsLeafA])

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertDictEqual(
            {
                "foo": ClsA.c1,
            },
            ClsD.CHILD_MAP)
        self.assertSetEqual(
            {ClsA.c1},
            ClsD.CHILD_PROPS)

    def test_collect_attr_property(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            attr1 = stanza_model.Attr("foo")
            attr2 = stanza_model.Attr("bar")
            attr3 = stanza_model.Attr("baz")

        self.assertDictEqual(
            {
                (None, "foo"): Cls.attr1,
                (None, "bar"): Cls.attr2,
                (None, "baz"): Cls.attr3,
            },
            Cls.ATTR_MAP)

    def test_forbid_ambiguous_attr(self):
        with self.assertRaises(TypeError):
            class Cls(metaclass=stanza_model.StanzaClass):
                attr1 = stanza_model.Attr("foo")
                attr2 = stanza_model.Attr("foo")

    def test_inheritance_attr(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            attr1 = stanza_model.Attr("foo")

        class ClsB(ClsA):
            attr2 = stanza_model.Attr("bar")

        self.assertDictEqual(
            {
                (None, "foo"): ClsA.attr1,
                (None, "bar"): ClsB.attr2,
            },
            ClsB.ATTR_MAP)

    def test_inheritance_attr_ambiguous(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            attr1 = stanza_model.Attr("foo")

        with self.assertRaises(TypeError):
            class ClsB(ClsA):
                attr2 = stanza_model.Attr("foo")

    def test_multi_inheritance_attr(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            attr1 = stanza_model.Attr("foo")

        class ClsB(metaclass=stanza_model.StanzaClass):
            attr2 = stanza_model.Attr("bar")

        class ClsC(ClsB, ClsA):
            attr3 = stanza_model.Attr("baz")

        self.assertDictEqual(
            {
                (None, "foo"): ClsA.attr1,
                (None, "bar"): ClsB.attr2,
                (None, "baz"): ClsC.attr3,
            },
            ClsC.ATTR_MAP)

    def test_multi_inheritance_attr_ambiguous(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            attr1 = stanza_model.Attr("foo")

        class ClsB(metaclass=stanza_model.StanzaClass):
            attr2 = stanza_model.Attr("foo")

        with self.assertRaises(TypeError):
            class ClsC(ClsB, ClsA):
                attr3 = stanza_model.Attr("baz")

    def test_diamond_inheritance_attr(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            attr = stanza_model.Attr("foo")

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertDictEqual(
            {
                (None, "foo"): ClsA.attr,
            },
            ClsD.ATTR_MAP)

    def test_collect_collector_property(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            prop = stanza_model.Collector()

        self.assertIs(
            Cls.prop,
            Cls.COLLECTOR_PROPERTY)

    def test_forbid_duplicate_collector_property(self):
        with self.assertRaises(TypeError):
            class Cls(metaclass=stanza_model.StanzaClass):
                propa = stanza_model.Collector()
                propb = stanza_model.Collector()

    def test_inheritance_collector_one_level(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            text = stanza_model.Collector()

        with self.assertRaises(TypeError):
            class ClsB(ClsA):
                text2 = stanza_model.Collector()

        class ClsB(ClsA):
            pass

        self.assertIs(ClsB.COLLECTOR_PROPERTY, ClsA.text)

    def test_multi_inheritance_collector(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            text = stanza_model.Collector()

        class ClsB(metaclass=stanza_model.StanzaClass):
            text2 = stanza_model.Collector()

        with self.assertRaises(TypeError):
            class ClsC(ClsA, ClsB):
                pass

    def test_diamond_inheritance_collector(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            text = stanza_model.Collector()

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertIs(ClsD.COLLECTOR_PROPERTY, ClsA.text)

    def test_forbid_duplicate_text_property(self):
        with self.assertRaises(TypeError):
            class Cls(metaclass=stanza_model.StanzaClass):
                TAG = "foo"
                propa = stanza_model.Text()
                propb = stanza_model.Text()

    def test_collect_child_list_property(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
        class ClsB(metaclass=stanza_model.StanzaClass):
            TAG = "bar"
        class ClsC(metaclass=stanza_model.StanzaClass):
            TAG = "baz"

        class Cls(metaclass=stanza_model.StanzaClass):
            cl1 = stanza_model.ChildList([ClsA, ClsB])
            cl2 = stanza_model.ChildList([ClsC])

        self.assertDictEqual(
            {
                ClsA.TAG: Cls.cl1,
                ClsB.TAG: Cls.cl1,
                ClsC.TAG: Cls.cl2,
            },
            Cls.CHILD_MAP)
        self.assertSetEqual(
            {Cls.cl1, Cls.cl2},
            Cls.CHILD_PROPS)

    def test_forbid_ambiguous_children_with_lists(self):
        class ClsA(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
        class ClsB(metaclass=stanza_model.StanzaClass):
            TAG = "foo"

        with self.assertRaisesRegexp(TypeError, "ambiguous Child properties"):
            class Cls(metaclass=stanza_model.StanzaClass):
                c1 = stanza_model.ChildList([ClsA])
                c2 = stanza_model.Child([ClsB])

    def test_collect_child_tag_property(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            ct = stanza_model.ChildTag(
                tags=[
                    "foo",
                    "bar"
                ],
                default_ns="uri:foo")

        self.assertDictEqual(
            {
                ("uri:foo", "foo"): Cls.ct,
                ("uri:foo", "bar"): Cls.ct,
            },
            Cls.CHILD_MAP)
        self.assertSetEqual(
            {Cls.ct},
            Cls.CHILD_PROPS)

    def test_ordered_child_props(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            c1 = stanza_model.ChildText((None, "a"))
            c2 = stanza_model.ChildText((None, "b"))
            c3 = stanza_model.ChildText((None, "c"))

        self.assertSequenceEqual(
            [
                Cls.c1,
                Cls.c2,
                Cls.c3,
            ],
            Cls.CHILD_PROPS)

    def test_register_child(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"

            child = stanza_model.Child([])

        class ClsA(metaclass=stanza_model.StanzaClass):
            TAG = "bar"

        class ClsB(metaclass=stanza_model.StanzaClass):
            TAG = "baz"

        class ClsC(metaclass=stanza_model.StanzaClass):
            TAG = "bar"

        Cls.register_child(Cls.child, ClsA)
        self.assertDictEqual(
            {
                (None, "bar"): Cls.child
            },
            Cls.CHILD_MAP)

        Cls.register_child(Cls.child, ClsB)
        self.assertDictEqual(
            {
                (None, "bar"): Cls.child,
                (None, "baz"): Cls.child,
            },
            Cls.CHILD_MAP)

        with self.assertRaises(ValueError):
            Cls.register_child(Cls.child, ClsC)

    def test_call_error_handler_on_broken_child(self):
        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

            text = stanza_model.Text(
                type_=stanza_types.Integer()
            )

        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"

            child = stanza_model.Child([Bar])

        Cls.stanza_error_handler = unittest.mock.MagicMock()

        gen = Cls.parse_events((None, "foo", {}))
        next(gen)
        gen.send(("start", None, "bar", {}))
        gen.send(("text", "foobar"))
        with self.assertRaises(ValueError):
            gen.send(("end", ))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.child,
                    [None, "bar", {}],
                    unittest.mock.ANY)
            ],
            Cls.stanza_error_handler.mock_calls
        )

    def test_call_error_handler_on_unexpected_child(self):
        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

            text = stanza_model.Text(
                type_=stanza_types.Integer()
            )

        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"
            UNKNOWN_CHILD_POLICY = stanza_model.UnknownChildPolicy.FAIL

            child = stanza_model.Child([Bar])

        Cls.stanza_error_handler = unittest.mock.MagicMock()

        gen = Cls.parse_events((None, "foo", {}))
        next(gen)
        with self.assertRaises(ValueError):
            gen.send(("start", None, "baz", {}))

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call(
                    None,
                    [None, "baz", {}],
                    None)
            ],
            Cls.stanza_error_handler.mock_calls
        )

    def test_call_error_handler_on_broken_text(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"

            text = stanza_model.Text(
                type_=stanza_types.Integer()
            )

        Cls.stanza_error_handler = unittest.mock.MagicMock()

        gen = Cls.parse_events((None, "foo", {}))
        next(gen)
        gen.send(("text", "foo"))
        gen.send(("text", "bar"))
        with self.assertRaises(ValueError):
            gen.send(("end",))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.text,
                    "foobar",
                    unittest.mock.ANY)
            ],
            Cls.stanza_error_handler.mock_calls
        )

    def test_call_error_handler_on_broken_attr(self):
        class Cls(metaclass=stanza_model.StanzaClass):
            TAG = "foo"

            attr = stanza_model.Attr(
                tag=(None, "attr"),
                type_=stanza_types.Integer()
            )

        Cls.stanza_error_handler = unittest.mock.MagicMock()

        gen = Cls.parse_events((None, "foo", {
            (None, "attr"): "foobar",
        }))
        with self.assertRaises(ValueError):
            next(gen)

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.attr,
                    "foobar",
                    unittest.mock.ANY)
            ],
            Cls.stanza_error_handler.mock_calls
        )


class TestStanzaObject(XMLTestCase):
    def _unparse_test(self, obj, tree):
        parent = etree.Element("foo")
        obj.unparse_to_node(parent)
        self.assertSubtreeEqual(
            tree,
            parent,
            strict_ordering=False
        )

    def setUp(self):
        class Cls(stanza_model.StanzaObject):
            TAG = "bar"

        self.Cls = Cls
        self.obj = Cls()

    def test_error_handler(self):
        self.obj.stanza_error_handler(
            None,
            None,
            None)

    def test_policies(self):
        self.assertEqual(
            stanza_model.UnknownChildPolicy.FAIL,
            self.Cls.UNKNOWN_CHILD_POLICY)
        self.assertEqual(
            stanza_model.UnknownAttrPolicy.FAIL,
            self.Cls.UNKNOWN_ATTR_POLICY)

    def test_property_storage(self):
        self.obj._stanza_props["key"] = "value"

    def test_unparse_to_node_create_node(self):
        self._unparse_test(
            self.obj,
            etree.fromstring("<foo><bar/></foo>")
        )

    def test_unparse_to_node_handle_text(self):
        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            text = stanza_model.Text()

        obj = Cls()
        obj.text = "foobar"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar>foobar</bar></foo>")
        )

    def test_unparse_to_node_handle_child(self):
        class ClsLeaf(stanza_model.StanzaObject):
            TAG = "baz"
            text = stanza_model.Text()

        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            child = stanza_model.Child([ClsLeaf])

        obj = Cls()
        obj.child = ClsLeaf()
        obj.child.text = "fnord"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><baz>fnord</baz></bar></foo>")
        )

    def test_unparse_to_node_handle_child_list(self):
        class ClsLeaf(stanza_model.StanzaObject):
            TAG = "baz"
            text = stanza_model.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            children = stanza_model.ChildList([ClsLeaf])

        obj = Cls()
        obj.children.append(ClsLeaf("a"))
        obj.children.append(ClsLeaf("b"))
        obj.children.append(ClsLeaf("c"))

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><baz>a</baz><baz>b</baz><baz>c</baz></bar></foo>")
        )

    def test_unparse_to_node_handle_child_text(self):
        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            body = stanza_model.ChildText("body")

        obj = Cls()
        obj.body = "foobar"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><body>foobar</body></bar></foo>")
        )

    def test_unparse_to_node_handle_collector(self):
        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            dump = stanza_model.Collector()

        obj = Cls()
        obj.dump.append(etree.fromstring("<foo/>"))
        obj.dump.append(etree.fromstring("<fnord/>"))

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><foo/><fnord/></bar></foo>")
        )

    def test_unparse_to_node_handle_child_map(self):
        class ClsLeafA(stanza_model.StanzaObject):
            TAG = "baz"
            text = stanza_model.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class ClsLeafB(stanza_model.StanzaObject):
            TAG = "fnord"
            text = stanza_model.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            children = stanza_model.ChildMap([ClsLeafA, ClsLeafB])

        obj = Cls()
        obj.children[ClsLeafA.TAG].append(ClsLeafA("a"))
        obj.children[ClsLeafA.TAG].append(ClsLeafA("b"))
        obj.children[ClsLeafB.TAG].append(ClsLeafB("1"))

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><baz>a</baz><baz>b</baz><fnord>1</fnord></bar></foo>")
        )

    def test_unparse_to_node_handle_attr(self):
        class Cls(stanza_model.StanzaObject):
            TAG = "bar"
            attr = stanza_model.Attr("baz")

        obj = Cls()
        obj.attr = "fnord"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar baz='fnord'/></foo>")
        )

    def tearDown(self):
        del self.obj
        del self.Cls


class Test_PropBase(unittest.TestCase):
    def setUp(self):
        self.default = object()
        class Cls(stanza_model.StanzaObject):
            prop = stanza_model._PropBase(
                default=self.default)
        self.Cls = Cls
        self.obj = Cls()

    def test_get_unset(self):
        self.assertIs(
            self.default,
            self.obj.prop)

    def test_set_get_cycle(self):
        self.obj.prop = "foo"
        self.assertEqual(
            "foo",
            self.obj.prop)

    def test_get_on_class(self):
        self.assertIsInstance(
            self.Cls.prop,
            stanza_model._PropBase)

    def test_validator_recv(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = stanza_model._PropBase(
            default=self.default,
            validator=validator,
            validate=stanza_model.ValidateMode.FROM_RECV)

        prop._set_from_recv(instance, "foo")
        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._stanza_props
        )

        prop._set_from_code(instance, "bar")
        self.assertDictEqual(
            {
                prop: "bar",
            },
            instance._stanza_props
        )

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop._set_from_recv(instance, "baz")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("baz"),
            ],
            validator.mock_calls)

    def test_validator_code(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = stanza_model._PropBase(
            default=self.default,
            validator=validator,
            validate=stanza_model.ValidateMode.FROM_CODE)

        prop._set_from_recv(instance, "foo")
        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._stanza_props
        )

        prop._set_from_code(instance, "bar")
        self.assertDictEqual(
            {
                prop: "bar",
            },
            instance._stanza_props
        )

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop._set_from_code(instance, "baz")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("bar"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("baz"),
            ],
            validator.mock_calls)

    def test_validator_always(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = stanza_model._PropBase(
            default=self.default,
            validator=validator,
            validate=stanza_model.ValidateMode.ALWAYS)

        prop._set_from_recv(instance, "foo")
        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._stanza_props
        )

        prop._set_from_code(instance, "bar")
        self.assertDictEqual(
            {
                prop: "bar",
            },
            instance._stanza_props
        )

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop._set_from_recv(instance, "baz")

        with self.assertRaises(ValueError):
            prop._set_from_code(instance, "fnord")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("bar"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("baz"),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("fnord"),
            ],
            validator.mock_calls)

    def test_descriptor_access_goes_through_code_setter(self):
        validator = unittest.mock.MagicMock()

        class Cls(stanza_model.StanzaObject):
            prop = stanza_model._PropBase(
                default=self.default,
                validator=validator,
                validate=stanza_model.ValidateMode.FROM_CODE)

        obj = Cls()
        obj.prop = "foo"
        self.assertEqual(
            "foo",
            obj.prop)

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            obj.prop = "bar"

        self.assertEqual(
            "foo",
            obj.prop)

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("bar"),
            ],
            validator.mock_calls)

    def tearDown(self):
        del self.obj
        del self.Cls
        del self.default


class TestText(XMLTestCase):
    def setUp(self):
        class ClsA(stanza_model.StanzaObject):
            test_str = stanza_model.Text(default="bar")
        class ClsB(stanza_model.StanzaObject):
            test_int = stanza_model.Text(type_=stanza_types.Integer())
        self.ClsA = ClsA
        self.ClsB = ClsB
        self.obja = ClsA()
        self.objb = ClsB()

    def test_default(self):
        self.assertEqual(
            "bar",
            self.obja.test_str)

    def test_string_from_node(self):
        self.ClsA.test_str.from_value(
            self.obja,
            "foo"
        )
        self.assertEqual(
            "foo",
            self.obja.test_str)

    def test_int_from_node(self):
        self.ClsB.test_int.from_value(
            self.objb,
            "123",
        )
        self.assertEqual(
            123,
            self.objb.test_int)

    def test_int_to_sax(self):
        dest = unittest.mock.MagicMock()
        self.objb.test_int = 123
        self.ClsB.test_int.to_sax(
            self.objb,
            dest)
        self.assertEqual(
            [
                unittest.mock.call.characters("123"),
            ],
            dest.mock_calls)

    def test_validates(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = stanza_model.Text(validator=validator)

        validator.validate.return_value = True
        prop.from_value(instance, "foo")

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop.from_value(instance, "foo")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
            ],
            validator.mock_calls)

    def test_to_sax_unset(self):
        instance = make_instance_mock()

        prop = stanza_model.Text(default="foo")
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.characters("foo"),
            ],
            dest.mock_calls)

        instance._stanza_props = {prop: None}
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

    def tearDown(self):
        del self.obja
        del self.objb
        del self.ClsA
        del self.ClsB


class TestChild(XMLTestCase):
    def setUp(self):
        class ClsLeaf(stanza_model.StanzaObject):
            TAG = "bar"

        class ClsA(stanza_model.StanzaObject):
            TAG = "foo"
            test_child = stanza_model.Child([ClsLeaf])

        self.ClsLeaf = ClsLeaf
        self.ClsA = ClsA

    def test_match_map(self):
        self.assertDictEqual(
            {self.ClsLeaf.TAG: self.ClsLeaf},
            self.ClsA.test_child.get_tag_map()
        )

    def test_forbid_duplicate_tags(self):
        class ClsLeaf2(stanza_model.StanzaObject):
            TAG = "bar"

        with self.assertRaisesRegexp(ValueError, "ambiguous children"):
            stanza_model.Child([self.ClsLeaf, ClsLeaf2])

    def test__register(self):
        class ClsLeaf2(stanza_model.StanzaObject):
            TAG = "baz"

        self.ClsA.test_child._register(ClsLeaf2)
        self.assertDictEqual(
            {
                (None, "bar"): self.ClsLeaf,
                (None, "baz"): ClsLeaf2
            },
            self.ClsA.test_child.get_tag_map()
        )

        class ClsLeafConflict(stanza_model.StanzaObject):
            TAG = "baz"

        with self.assertRaisesRegexp(ValueError, "ambiguous children"):
            self.ClsA.test_child._register(ClsLeafConflict)

    def test_from_events(self):
        dest = []
        def mock_fun(ev_args):
            dest.append(ev_args)
            while True:
                value = yield
                dest.append(value)
                if value[0] == "stop":
                    return "bar"

        Cls = unittest.mock.MagicMock()
        Cls.TAG = None, "foo"
        Cls.parse_events = mock_fun

        prop = stanza_model.Child([Cls])

        instance = make_instance_mock()

        gen = prop.from_events(instance, (None, "foo", {}))
        next(gen)
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("stop",))
        self.assertEqual(
            "bar",
            ctx.exception.value
        )
        self.assertSequenceEqual(
            [
                (None, "foo", {}),
                ("stop",)
            ],
            dest)
        self.assertDictEqual(
            {prop: "bar"},
            instance._stanza_props)

    def test_to_sax(self):
        dest = unittest.mock.MagicMock()
        obj = self.ClsA()
        obj.test_child = unittest.mock.MagicMock()
        self.ClsA.test_child.to_sax(obj, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.unparse_to_sax(dest)
            ],
            obj.test_child.mock_calls
        )

    def test_to_sax_unset(self):
        dest = unittest.mock.MagicMock()
        obj = self.ClsA()
        obj.test_child = None
        self.ClsA.test_child.to_sax(obj, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

    def tearDown(self):
        del self.ClsA
        del self.ClsLeaf


class TestChildList(XMLTestCase):
    def setUp(self):
        class ClsLeafA(stanza_model.StanzaObject):
            TAG = "bar"

        class ClsLeafB(stanza_model.StanzaObject):
            TAG = "baz"

        class Cls(stanza_model.StanzaObject):
            TAG = "foo"
            children = stanza_model.ChildList([ClsLeafA, ClsLeafB])

        self.Cls = Cls
        self.ClsLeafA = ClsLeafA
        self.ClsLeafB = ClsLeafB

    def test_from_events(self):
        results = []

        def catch_result(value):
            results.append(value)

        obj = self.Cls()

        sd = stanza_model.SAXDriver(
            functools.partial(from_wrapper, self.Cls.children.from_events, obj),
            on_emit=catch_result
        )

        subtrees = [etree.Element(s) for s in ["bar", "bar", "baz", "bar"]]

        for subtree in subtrees:
            lxml.sax.saxify(subtree, sd)

        self.assertSequenceEqual(
            results,
            obj.children)

        self.assertEqual(4, len(obj.children))

        self.assertIsInstance(obj.children[0], self.ClsLeafA)
        self.assertIsInstance(obj.children[1], self.ClsLeafA)
        self.assertIsInstance(obj.children[2], self.ClsLeafB)
        self.assertIsInstance(obj.children[3], self.ClsLeafA)

    def test_to_sax(self):
        dest = unittest.mock.MagicMock()

        obj = self.Cls()
        obj.children.append(self.ClsLeafA())
        obj.children.append(self.ClsLeafB())
        obj.children.append(self.ClsLeafA())
        obj.children.append(self.ClsLeafA())

        self.Cls.children.to_sax(obj, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "bar"), None, {}),
                unittest.mock.call.endElementNS((None, "bar"), None),
                unittest.mock.call.startElementNS((None, "baz"), None, {}),
                unittest.mock.call.endElementNS((None, "baz"), None),
                unittest.mock.call.startElementNS((None, "bar"), None, {}),
                unittest.mock.call.endElementNS((None, "bar"), None),
                unittest.mock.call.startElementNS((None, "bar"), None, {}),
                unittest.mock.call.endElementNS((None, "bar"), None),
            ],
            dest.mock_calls)

    def test_assign_enforces_list(self):
        obj = self.Cls()
        with self.assertRaises(TypeError):
            obj.children = 123
        with self.assertRaises(TypeError):
            obj.children = "foo"
        l = []
        obj.children = l
        self.assertIs(
            l,
            obj.children
        )

    def tearDown(self):
        del self.ClsLeafB
        del self.ClsLeafA
        del self.Cls


class TestCollector(XMLTestCase):
    def test_from_events(self):
        instance = make_instance_mock()

        prop = stanza_model.Collector()

        subtree1 = etree.fromstring("<foo/>")
        subtree2 = etree.fromstring("<bar a='baz'>fnord</bar>")
        subtree3 = etree.fromstring("<baz>prefix: <a/><b c='something'/><d i='am running out of'>dummy texts</d>to insert</baz>")

        subtrees = [subtree1, subtree2, subtree3]

        for subtree in subtrees:
            drive_from_events(prop.from_events, instance, subtree)

        for result, subtree in zip(instance._stanza_props[prop],
                                   subtrees):
            self.assertSubtreeEqual(
                subtree,
                result)

    def test_assign_enforces_list(self):
        class Cls(stanza_model.StanzaObject):
            children = stanza_model.Collector()

        obj = Cls()
        with self.assertRaises(TypeError):
            obj.children = 123
        with self.assertRaises(TypeError):
            obj.children = "foo"
        l = []
        obj.children = l
        self.assertIs(
            l,
            obj.children
        )

    def test_to_node(self):
        prop = stanza_model.Collector()

        subtree1 = etree.fromstring("<foo/>")
        subtree2 = etree.fromstring("<bar a='baz'>fnord</bar>")
        subtree3 = etree.fromstring("<baz><a/><b c='something'/><d i='am running out of'>dummy texts</d>to insert</baz>")

        instance = make_instance_mock({
            prop: [
                subtree1,
                subtree2,
                subtree3,
            ]
        })

        parent_compare = etree.Element("root")
        parent_compare.extend([subtree1, subtree2, subtree3])

        parent_generated = etree.Element("root")
        prop.to_node(instance, parent_generated)

        self.assertSubtreeEqual(
            parent_compare,
            parent_generated)


class TestAttr(XMLTestCase):
    def test_tag_attribute(self):
        prop = stanza_model.Attr("foo")
        self.assertEqual(
            (None, "foo"),
            prop.tag
        )

        prop = stanza_model.Attr((None, "foo"))
        self.assertEqual(
            (None, "foo"),
            prop.tag
        )

        prop = stanza_model.Attr(("bar", "foo"))
        self.assertEqual(
            ("bar", "foo"),
            prop.tag
        )

    def test_from_value_and_type(self):
        instance = make_instance_mock()

        prop = stanza_model.Attr("foo", type_=stanza_types.Integer())
        prop.from_value(instance, "123")

        self.assertDictEqual(
            {
                prop: 123,
            },
            instance._stanza_props
        )

    def test_to_dict(self):
        d = {}

        prop = stanza_model.Attr("foo", type_=stanza_types.Bool())
        instance = make_instance_mock({prop: True})

        prop.to_dict(instance, d)
        self.assertDictEqual(
            {
                (None, "foo"): "true"
            },
            d)

    def test_to_dict_unset(self):
        prop = stanza_model.Attr("foo", default="bar")
        instance = make_instance_mock()

        d = {}
        prop.to_dict(instance, d)
        self.assertDictEqual(
            {
                (None, "foo"): "bar"
            },
            d)

        instance._stanza_props = {prop: None}

        d = {}
        prop.to_dict(instance, d)
        self.assertDictEqual(
            {
            },
            d)

    def test_validates(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = stanza_model.Attr("foo", validator=validator)

        validator.validate.return_value = True
        prop.from_value(instance, "foo")

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop.from_value(instance, "foo")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
            ],
            validator.mock_calls)


class TestChildText(XMLTestCase):
    def test_init(self):
        type_mock = unittest.mock.MagicMock()
        validator_mock = unittest.mock.MagicMock()

        prop = stanza_model.ChildText(
            tag="body",
            type_=type_mock,
            validator=validator_mock)
        self.assertEqual(
            (None, "body"),
            prop.tag)
        self.assertIs(
            type_mock,
            prop.type_)
        self.assertIs(
            validator_mock,
            prop.validator)

    def test_from_events_with_type_and_validation(self):
        type_mock = unittest.mock.MagicMock()
        validator_mock = unittest.mock.MagicMock()

        instance = make_instance_mock()

        prop = stanza_model.ChildText(
            "body",
            type_=type_mock,
            validator=validator_mock)

        subtree = etree.fromstring("<body>foo</body>")

        drive_from_events(prop.from_events, instance, subtree)

        self.assertSequenceEqual(
            [
                unittest.mock.call.parse("foo"),
            ],
            type_mock.mock_calls)
        self.assertDictEqual(
            {
                prop: type_mock.parse("foo"),
            },
            instance._stanza_props)
        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate(type_mock.parse("foo")),
                unittest.mock.call.validate().__bool__(),
            ],
            validator_mock.mock_calls)
        self.assertSequenceEqual(
            [],
            instance.mock_calls)

    def test_from_events_validates(self):
        type_mock = unittest.mock.MagicMock()
        validator_mock = unittest.mock.MagicMock()

        instance = make_instance_mock()

        prop = stanza_model.ChildText(
            "body",
            type_=type_mock,
            validator=validator_mock)

        subtree = etree.fromstring("<body>foo</body>")
        validator_mock.validate.return_value = False

        with self.assertRaises(ValueError):
            drive_from_events(prop.from_events, instance, subtree)

    def test_child_policy_default(self):
        prop = stanza_model.ChildText("body")
        self.assertEqual(
            stanza_model.UnknownChildPolicy.FAIL,
            prop.child_policy)

    def test_enforce_child_policy_fail(self):
        instance = make_instance_mock()

        prop = stanza_model.ChildText(
            "body",
            child_policy=stanza_model.UnknownChildPolicy.FAIL)
        subtree = etree.fromstring("<body>foo<bar/></body>")

        with self.assertRaises(ValueError):
            drive_from_events(prop.from_events, instance, subtree)

        self.assertFalse(instance._stanza_props)

    def test_enforce_child_policy_drop(self):
        instance = make_instance_mock()

        prop = stanza_model.ChildText(
            "body",
            child_policy=stanza_model.UnknownChildPolicy.DROP)
        subtree = etree.fromstring("<body>foo<bar/>bar</body>")
        drive_from_events(prop.from_events, instance, subtree)

        self.assertDictEqual(
            {
                prop: "foobar",
            },
            instance._stanza_props)

    def test_attr_policy_default(self):
        prop = stanza_model.ChildText("body")
        self.assertEqual(
            stanza_model.UnknownAttrPolicy.FAIL,
            prop.attr_policy)

    def test_enforce_attr_policy_fail(self):
        instance = make_instance_mock()

        prop = stanza_model.ChildText(
            "body",
            attr_policy=stanza_model.UnknownAttrPolicy.FAIL)
        subtree = etree.fromstring("<body a='bar'>foo</body>")

        with self.assertRaises(ValueError):
            drive_from_events(prop.from_events, instance, subtree)

        self.assertFalse(instance._stanza_props)

    def test_enforce_attr_policy_drop(self):
        instance = make_instance_mock()

        prop = stanza_model.ChildText(
            "body",
            attr_policy=stanza_model.UnknownAttrPolicy.DROP)
        subtree = etree.fromstring("<body a='bar'>foo</body>")

        drive_from_events(prop.from_events, instance, subtree)

        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._stanza_props)

    def test_to_sax(self):
        dest = unittest.mock.MagicMock()

        type_mock = unittest.mock.MagicMock()
        type_mock.format.return_value = "foo"

        prop = stanza_model.ChildText(
            "body",
            type_=type_mock
        )

        instance = make_instance_mock({
            prop: "foo"
        })

        parent = etree.Element("root")
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "body"), None, {}),
                unittest.mock.call.characters("foo"),
                unittest.mock.call.endElementNS((None, "body"), None)
            ],
            dest.mock_calls)
        self.assertSequenceEqual(
            [
                unittest.mock.call.format("foo"),
            ],
            type_mock.mock_calls)

    def test_to_sax_declare_prefix(self):
        prefix = object()
        dest = unittest.mock.MagicMock()

        type_mock = unittest.mock.MagicMock()
        type_mock.format.return_value = "foo"

        prop = stanza_model.ChildText(
            ("uri:foo", "body"),
            type_=type_mock,
            declare_prefix=prefix
        )

        instance = make_instance_mock({
            prop: "foo"
        })

        parent = etree.Element("root")
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startPrefixMapping(prefix, "uri:foo"),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "body"),
                    None,
                    {}),
                unittest.mock.call.characters("foo"),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "body"),
                    None),
                unittest.mock.call.endPrefixMapping(prefix)
            ],
            dest.mock_calls)
        self.assertSequenceEqual(
            [
                unittest.mock.call.format("foo"),
            ],
            type_mock.mock_calls)

    def test_to_sax_unset(self):
        prop = stanza_model.ChildText("body", default="foo")

        instance = make_instance_mock()

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "body"), None, {}),
                unittest.mock.call.characters("foo"),
                unittest.mock.call.endElementNS((None, "body"), None)
            ],
            dest.mock_calls)

        instance._stanza_props = {prop: None}
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

        instance._stanza_props = {prop: ""}
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "body"), None, {}),
                unittest.mock.call.characters(""),
                unittest.mock.call.endElementNS((None, "body"), None)
            ],
            dest.mock_calls)


class TestChildMap(XMLTestCase):
    def test_class_access_returns_property(self):
        prop = stanza_model.ChildMap([])
        class Foo(stanza_model.StanzaObject):
            cm = prop

        self.assertIs(
            prop,
            Foo.cm)

    def test_from_events_from_init(self):
        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

        instance = make_instance_mock()

        prop = stanza_model.ChildMap([Foo, Bar])

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar/>")
        )
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo/>")
        )
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar/>")
        )

        self.assertIn(prop, instance._stanza_props)
        resultmap = instance._stanza_props[prop]
        self.assertEqual(2, len(resultmap))
        self.assertIn(Bar.TAG, resultmap)
        self.assertIn(Foo.TAG, resultmap)

        bar_results = resultmap[Bar.TAG]
        self.assertEqual(2, len(bar_results))
        self.assertIsInstance(bar_results[0], Bar)
        self.assertIsInstance(bar_results[1], Bar)

        foo_results = resultmap[Foo.TAG]
        self.assertEqual(1, len(foo_results))
        self.assertIsInstance(foo_results[0], Foo)

    def test_assign_enforces_dict(self):
        class Cls(stanza_model.StanzaObject):
            children = stanza_model.ChildMap([])
        obj = Cls()

        with self.assertRaises(TypeError):
            obj.children = 123
        with self.assertRaises(TypeError):
            obj.children = "foo"
        d = {}
        obj.children = d
        self.assertIs(
            d,
            obj.children
        )

    def test_to_node(self):
        # we run the test through to_node here, to avoid ordering issues with
        # the dict.

        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

            attr = stanza_model.Attr("a")

            def __init__(self, a=None):
                super().__init__()
                self.attr = a

        prop = stanza_model.ChildMap([Foo, Bar])

        instance = make_instance_mock({
            prop: {
                Bar.TAG: [Bar()],
                Foo.TAG: [Foo(a=1), Foo(a=2)]
            }
        })

        parent = etree.Element("root")
        prop.to_node(instance, parent)
        self.assertSubtreeEqual(
            etree.fromstring("<root><foo a='1'/><foo a='2'/><bar/></root>"),
            parent)


class TestChildTag(unittest.TestCase):
    def test_from_events(self):
        instance = make_instance_mock()

        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo")

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'/>")
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._stanza_props
        )

    def test_child_policy_fail(self):
        instance = make_instance_mock()
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            child_policy=stanza_model.UnknownChildPolicy.FAIL)

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo xmlns='uri:foo'><bar/></foo>")
            )

        self.assertFalse(instance._stanza_props)

    def test_child_policy_drop(self):
        instance = make_instance_mock()
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            child_policy=stanza_model.UnknownChildPolicy.DROP)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'><bar/></foo>")
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._stanza_props
        )

    def test_attr_policy_fail(self):
        instance = make_instance_mock()
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            attr_policy=stanza_model.UnknownAttrPolicy.FAIL)

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo a='b' xmlns='uri:foo'/>")
            )

        self.assertFalse(instance._stanza_props)

    def test_attr_policy_drop(self):
        instance = make_instance_mock()
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            attr_policy=stanza_model.UnknownAttrPolicy.DROP)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo a='b' xmlns='uri:foo'/>")
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._stanza_props
        )

    def test_text_policy_fail(self):
        instance = make_instance_mock()
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            text_policy=stanza_model.UnknownTextPolicy.FAIL)

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo xmlns='uri:foo'>bar</foo>")
            )

        self.assertFalse(instance._stanza_props)

    def test_text_policy_drop(self):
        instance = make_instance_mock()
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            text_policy=stanza_model.UnknownTextPolicy.DROP)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'>bar</foo>")
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._stanza_props
        )

    def test_to_sax(self):
        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo")

        instance = make_instance_mock({
            prop: ("uri:foo", "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None)
            ],
            dest.mock_calls)

    def test_to_sax_declare_prefix(self):
        prefix = object()

        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            declare_prefix=prefix)

        instance = make_instance_mock({
            prop: ("uri:foo", "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startPrefixMapping(prefix, "uri:foo"),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None),
                unittest.mock.call.endPrefixMapping(prefix),
            ],
            dest.mock_calls)

    def test_to_sax_declare_prefix_skips_if_namespaceless(self):
        prefix = object()

        prop = stanza_model.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            declare_prefix=prefix)

        instance = make_instance_mock({
            prop: (None, "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    (None, "bar"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    (None, "bar"),
                    None),
            ],
            dest.mock_calls)


class Testdrop_handler(unittest.TestCase):
    def test_drop_handler(self):
        result = object()

        def catch_result(value):
            nonlocal result
            result = value

        sd = stanza_model.SAXDriver(
            functools.partial(from_wrapper, stanza_model.drop_handler),
            on_emit=catch_result)

        tree = etree.fromstring("<foo><bar a='fnord'/><baz>keks</baz></foo>")
        lxml.sax.saxify(tree, sd)

        self.assertIsNone(result)


class Testenforce_unknown_child_policy(unittest.TestCase):
    @unittest.mock.patch("asyncio_xmpp.stanza_model.drop_handler")
    def test_drop_policy(self, drop_handler):
        drop_handler.return_value = []
        gen = stanza_model.enforce_unknown_child_policy(
            stanza_model.UnknownChildPolicy.DROP,
            (None, "foo", {}))
        with self.assertRaises(StopIteration):
            next(gen)
        self.assertSequenceEqual(
            [
                unittest.mock.call((None, "foo", {})),
            ],
            drop_handler.mock_calls
        )

    def test_fail_policy(self):
        gen = stanza_model.enforce_unknown_child_policy(
            stanza_model.UnknownChildPolicy.FAIL,
            (None, "foo", {}))
        with self.assertRaises(ValueError):
            next(gen)


class TestSAXDriver(unittest.TestCase):
    def setUp(self):
        self.l = []

    def catchall(self):
        while True:
            try:
                self.l.append((yield))
            except GeneratorExit as exc:
                self.l.append(exc)
                raise

    def test_forwards_startstop_events(self):
        tree = etree.fromstring("<foo/>")
        sd = stanza_model.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_text_events(self):
        tree = etree.fromstring("<foo>bar</foo>")
        sd = stanza_model.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("text", "bar"),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_nested_elements(self):
        tree = etree.fromstring("<foo><bar/></foo>")
        sd = stanza_model.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("start", None, "bar", {}),
                ("end",),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_attributes(self):
        tree = etree.fromstring("<foo><bar a='b'/></foo>")
        sd = stanza_model.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("start", None, "bar", {(None, "a"): "b"}),
                ("end",),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_namespaces(self):
        tree = etree.fromstring("<foo xmlns='uri:bar' />")
        sd = stanza_model.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", "uri:bar", "foo", {}),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_collect_result(self):
        l = []
        results = []
        def returning_coroutine():
            nonlocal l
            while True:
                data = yield
                l.append(data)
                if data[0] == "end":
                    return "foo"

        def catch_result(value):
            nonlocal results
            results.append(value)

        tree = etree.fromstring("<foo/>")
        sd = stanza_model.SAXDriver(
            returning_coroutine,
            on_emit=catch_result)
        lxml.sax.saxify(tree, sd)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("end",),
            ]*2,
            l)
        self.assertSequenceEqual(
            ["foo"]*2,
            results)

        sd.close()

    def test_close_forwards_to_generator(self):
        sd = stanza_model.SAXDriver(self.catchall)
        sd.startElementNS((None, "foo"), "foo", {})
        sd.close()

        self.assertIsInstance(self.l[-1], GeneratorExit)

    def tearDown(self):
        del self.l


class ChildTag(XMLTestCase):
    def setUp(self):
        self.prop = stanza_model.ChildTag(
            [
                "foo",
                ("uri:foo", "bar"),
                "baz"
            ],
            default_ns="uri:bar")

    def test_init(self):
        self.assertSetEqual(
            {
                ("uri:bar", "foo"),
                ("uri:foo", "bar"),
                ("uri:bar", "baz"),
            },
            self.prop.get_tag_map()
        )

    def test_valdiator(self):
        self.assertTrue(self.prop.validator.validate(("uri:bar", "foo")))
        self.assertFalse(self.prop.validator.validate(("uri:foo", "foo")))

    def test_type(self):
        self.assertEqual(
            (None, "foo"),
            self.prop.type_.parse("foo")
        )
        self.assertEqual(
            "{uri:bar}foo",
            self.prop.type_.format(("uri:bar", "foo"))
        )

    def test_from_events(self):
        instance = make_instance_mock()

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar'/>")
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._stanza_props)

    def test_from_events_text_policy_fail(self):
        instance = make_instance_mock()
        self.prop.text_policy = stanza_model.UnknownTextPolicy.FAIL

        with self.assertRaises(ValueError):
            drive_from_events(
                self.prop.from_events, instance,
                etree.fromstring("<foo xmlns='uri:bar'>text</foo>")
            )
        self.assertFalse(instance._stanza_props)

    def test_from_events_text_policy_drop(self):
        instance = make_instance_mock()
        self.prop.text_policy = stanza_model.UnknownTextPolicy.DROP

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar'>text</foo>")
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._stanza_props)

    def test_from_events_child_policy_fail(self):
        instance = make_instance_mock()
        self.prop.child_policy = stanza_model.UnknownChildPolicy.FAIL

        with self.assertRaises(ValueError):
            drive_from_events(
                self.prop.from_events, instance,
                etree.fromstring("<foo xmlns='uri:bar'><bar/></foo>")
            )
        self.assertFalse(instance._stanza_props)

    def test_from_events_child_policy_drop(self):
        instance = make_instance_mock()
        self.prop.child_policy = stanza_model.UnknownChildPolicy.DROP

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar'><bar/></foo>")
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._stanza_props)

    def test_from_events_attr_policy_fail(self):
        instance = make_instance_mock()
        self.prop.attr_policy = stanza_model.UnknownAttrPolicy.FAIL

        with self.assertRaises(ValueError):
            drive_from_events(
                self.prop.from_events, instance,
                etree.fromstring("<foo xmlns='uri:bar' a='bar'/>")
            )
        self.assertFalse(instance._stanza_props)

    def test_from_events_attr_policy_drop(self):
        instance = make_instance_mock()
        self.prop.attr_policy = stanza_model.UnknownAttrPolicy.DROP

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar' a='bar'/>")
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._stanza_props)

    def test_to_sax(self):
        instance = make_instance_mock({
            self.prop: ("uri:bar", "foo")
        })

        dest = unittest.mock.MagicMock()
        self.prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(("uri:bar", "foo"), None, {}),
                unittest.mock.call.endElementNS(("uri:bar", "foo"), None),
            ],
            dest.mock_calls)

    def test_to_sax_unset(self):
        instance = make_instance_mock({
            self.prop: None
        })

        dest = unittest.mock.MagicMock()
        self.prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

    def test_validate_from_code(self):
        class ClsWNone(stanza_model.StanzaObject):
            prop = stanza_model.ChildTag(
                self.prop.get_tag_map(),
                allow_none=True)

        class ClsWONone(stanza_model.StanzaObject):
            prop = stanza_model.ChildTag(
                self.prop.get_tag_map(),
                default=("uri:bar", "foo"),
                allow_none=False)

        w_none = ClsWNone()
        wo_none = ClsWONone()

        with self.assertRaises(ValueError):
            wo_none.prop = None
        with self.assertRaises(ValueError):
            wo_none.prop = ("foo", "bar")
        with self.assertRaises(ValueError):
            wo_none.prop = "foo"
        with self.assertRaises(ValueError):
            w_none.prop = ("foo", "bar")
        with self.assertRaises(ValueError):
            w_none.prop = "foo"

    def tearDown(self):
        del self.prop


class TestStanzaParser(XMLTestCase):
    def run_parser(self, classes, tree):
        results = []

        def catch_result(value):
            nonlocal results
            results.append(value)

        def fail_hard(*args):
            raise AssertionError("this should not be reached")

        parser = stanza_model.StanzaParser()
        for cls in classes:
            parser.add_class(cls, catch_result)

        sd = stanza_model.SAXDriver(
            parser,
            on_emit=fail_hard
        )
        lxml.sax.saxify(tree, sd)

        return results

    def run_parser_one(self, stanza_cls, tree):
        results = self.run_parser(stanza_cls, tree)
        self.assertEqual(1, len(results))
        return results[0]

    def test_parse_text(self):
        class TestStanza(stanza_model.StanzaObject):
            TAG = "uri:bar", "foo"
            contents = stanza_model.Text()
        tree = etree.fromstring("<foo xmlns='uri:bar'>bar</foo>")
        result = self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(result, TestStanza)
        self.assertEqual(result.contents, "bar")

    def test_parse_text_split_in_multiple_events(self):
        class Dummy(stanza_model.StanzaObject):
            TAG = "uri:bar", "dummy"

        class TestStanza(stanza_model.StanzaObject):
            TAG = "uri:bar", "foo"

            contents = stanza_model.Text()
            _ = stanza_model.Child([Dummy])

        tree = etree.fromstring("<foo xmlns='uri:bar'>bar<dummy/>baz</foo>")
        result = self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(result, TestStanza)
        self.assertEqual(result.contents, "barbaz")

    def test_handle_unknown_tag_at_toplevel(self):
        tree = etree.fromstring("<foo />")
        class TestStanza(stanza_model.StanzaObject):
            TAG = "uri:bar", "foo"

        with self.assertRaises(stanza_model.UnknownTopLevelTag) as ctx:
            self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertSequenceEqual(
            (None, "foo", {}),
            ctx.exception.ev_args
        )

    def test_handle_unknown_tag_at_non_toplevel(self):
        tree = etree.fromstring("<foo><bar/></foo>")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_handle_unknown_tag_at_non_toplevel_with_drop_policy(self):
        tree = etree.fromstring("<foo><bar/></foo>")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"
            UNKNOWN_CHILD_POLICY = stanza_model.UnknownChildPolicy.DROP

        self.run_parser_one([TestStanza], tree)

    def test_parse_using_collector(self):
        tree = etree.fromstring("<foo><bar/></foo>")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"
            coll = stanza_model.Collector()

        result = self.run_parser_one([TestStanza], tree)
        self.assertEqual(1, len(result.coll))
        self.assertSubtreeEqual(
            etree.fromstring("<bar/>"),
            result.coll[0])

    def test_handle_unknown_attribute(self):
        tree = etree.fromstring("<foo a='bar' />")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_handle_unknown_attribute_with_drop_policy(self):
        tree = etree.fromstring("<foo a='bar' />")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"
            UNKNOWN_ATTR_POLICY = stanza_model.UnknownAttrPolicy.DROP

        self.run_parser_one([TestStanza], tree)

    def test_handle_unknown_text(self):
        tree = etree.fromstring("<foo>bar</foo>")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_handle_missing_attribute(self):
        tree = etree.fromstring("<foo/>")
        class TestStanza(stanza_model.StanzaObject):
            TAG = None, "foo"
            attr = stanza_model.Attr("a", required=True)

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_parse_simple_with_another_attribute(self):
        class TestStanza(stanza_model.StanzaObject):
            TAG = "uri:bar", "foo"
            text = stanza_model.Text()
        tree = etree.fromstring("<foo xmlns='uri:bar'>bar</foo>")
        result = self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(result, TestStanza)
        self.assertEqual(result.text, "bar")

    def test_parse_detect_class(self):
        class TestStanzaA(stanza_model.StanzaObject):
            TAG = "uri:bar", "a"

        class TestStanzaB(stanza_model.StanzaObject):
            TAG = "uri:bar", "b"

        tree = etree.fromstring("<a xmlns='uri:bar' />")
        result = self.run_parser_one([TestStanzaA, TestStanzaB], tree)
        self.assertIsInstance(result, TestStanzaA)

        tree = etree.fromstring("<b xmlns='uri:bar' />")
        result = self.run_parser_one([TestStanzaA, TestStanzaB], tree)
        self.assertIsInstance(result, TestStanzaB)

    def test_parse_child(self):
        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

            child = stanza_model.Child([Bar])

        tree = etree.fromstring("<foo><bar/></foo>")
        result = self.run_parser_one([Foo], tree)
        self.assertIsInstance(result, Foo)
        self.assertIsInstance(result.child, Bar)

    def test_parse_attribute(self):
        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

            attr = stanza_model.Attr("bar")

        tree = etree.fromstring("<foo bar='baz'/>")
        result = self.run_parser_one([Foo], tree)
        self.assertEqual(
            "baz",
            result.attr)

    def test_parse_attribute_nested(self):
        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

            attr = stanza_model.Attr("a")

        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

            attr = stanza_model.Attr("a")
            child = stanza_model.Child([Bar])

        tree = etree.fromstring("<foo a='baz'><bar a='fnord'/></foo>")
        result = self.run_parser_one([Foo], tree)
        self.assertEqual(
            "baz",
            result.attr)
        self.assertEqual(
            "fnord",
            result.child.attr)

    def test_parse_child_list(self):
        class ClsLeafA(stanza_model.StanzaObject):
            TAG = "bar"

            attr = stanza_model.Attr("a")

        class ClsLeafB(stanza_model.StanzaObject):
            TAG = "baz"

            attr = stanza_model.Attr("b")

        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

            cl = stanza_model.ChildList([ClsLeafA, ClsLeafB])

        tree = etree.fromstring("<foo><bar a='1'/><baz b='2'/><bar a='3'/><bar a='4'/></foo>")
        result = self.run_parser_one([Foo], tree)
        self.assertEqual(4, len(result.cl))

        expected = [
            (ClsLeafA, "1"),
            (ClsLeafB, "2"),
            (ClsLeafA, "3"),
            (ClsLeafA, "4"),
        ]

        for i, (child, (cls, value)) in enumerate(zip(result.cl, expected)):
            self.assertIsInstance(child, cls, "child {}".format(i))
            self.assertEqual(child.attr, value, "child {}".format(i))

    def test_parse_child_with_post_register(self):
        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

            child = stanza_model.Child([])

        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

        Foo.register_child(Foo.child, Bar)

        tree = etree.fromstring("<foo><bar/></foo>")
        result = self.run_parser_one([Foo], tree)

        self.assertIsInstance(result.child, Bar)

    def test_parse_child_text(self):
        class Foo(stanza_model.StanzaObject):
            TAG = "foo"
            body = stanza_model.ChildText("body")

        tree = etree.fromstring("<foo><body>foobar</body></foo>")
        result = self.run_parser_one([Foo], tree)

        self.assertEqual(
            "foobar",
            result.body)

    def test_add_class(self):
        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

        cb1, cb2 = object(), object()

        p = stanza_model.StanzaParser()
        p.add_class(Foo, cb1)
        p.add_class(Bar, cb2)

        self.assertDictEqual(
            {
                Foo.TAG: (Foo, cb1),
                Bar.TAG: (Bar, cb2)
            },
            p.get_tag_map()
        )

    def test_add_class_forbid_duplicate_tags(self):
        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

        class Bar(stanza_model.StanzaObject):
            TAG = "foo"

        p = stanza_model.StanzaParser()
        p.add_class(Foo, None)
        with self.assertRaises(ValueError):
            p.add_class(Bar, None)

    def test_remove_class(self):
        class Foo(stanza_model.StanzaObject):
            TAG = "foo"

        class Bar(stanza_model.StanzaObject):
            TAG = "bar"

        p = stanza_model.StanzaParser()
        p.add_class(Foo, None)
        p.add_class(Bar, None)

        p.remove_class(Bar)
        self.assertDictEqual(
            {
                Foo.TAG: (Foo, None),
            },
            p.get_tag_map()
        )
        p.remove_class(Foo)
        self.assertFalse(p.get_tag_map())
