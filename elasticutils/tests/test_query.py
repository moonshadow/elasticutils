from nose.tools import eq_

from elasticutils import F, S, InvalidFieldActionError
from elasticutils.tests import FakeModel, ElasticTestCase, facet_counts_dict


class HasDataTestCase(ElasticTestCase):
    @classmethod
    def setup_class(cls):
        super(HasDataTestCase, cls).setup_class()
        if cls.skip_tests:
            return

        es = cls.get_es()
        es.delete_index_if_exists(cls.index_name)

        data1 = FakeModel(id=1, foo='bar', tag='awesome', width='2')
        data2 = FakeModel(id=2, foo='barf', tag='boring', width='7')
        data3 = FakeModel(id=3, foo='car', tag='awesome', width='5')
        data4 = FakeModel(id=4, foo='duck', tag='boat', width='11')
        data5 = FakeModel(id=5, foo='train car', tag='awesome', width='7')

        for data in (data1, data2, data3, data4, data5):
            es.index(data.__dict__, cls.index_name, FakeModel._meta.db_table,
                    bulk=True, id=data.id)
        es.refresh()

    @classmethod
    def teardown_class(cls):
        super(HasDataTestCase, cls).teardown_class()
        if cls.skip_tests:
            return

        es = cls.get_es()
        es.delete_index(cls.index_name)

    def get_s(self):
        return S(FakeModel).indexes(self.index_name)


class QueryTest(HasDataTestCase):
    def test_q(self):
        eq_(len(self.get_s().query(foo='bar')), 1)
        eq_(len(self.get_s().query(foo='car')), 2)

    def test_q_all(self):
        eq_(len(self.get_s()), 5)

    def test_filter_empty_f(self):
        eq_(len(self.get_s().filter(F() | F(tag='awesome'))), 3)
        eq_(len(self.get_s().filter(F() & F(tag='awesome'))), 3)
        eq_(len(self.get_s().filter(F() | F() | F(tag='awesome'))), 3)
        eq_(len(self.get_s().filter(F() & F() & F(tag='awesome'))), 3)
        eq_(len(self.get_s().filter(F())), 5)

    def test_filter(self):
        eq_(len(self.get_s().filter(tag='awesome')), 3)
        eq_(len(self.get_s().filter(F(tag='awesome'))), 3)

    def test_filter_and(self):
        eq_(len(self.get_s().filter(tag='awesome', foo='bar')), 1)
        eq_(len(self.get_s().filter(tag='awesome').filter(foo='bar')), 1)
        eq_(len(self.get_s().filter(F(tag='awesome') & F(foo='bar'))), 1)

    def test_filter_or(self):
        eq_(len(self.get_s().filter(F(tag='awesome') | F(tag='boat'))), 4)

    def test_filter_or_3(self):
        eq_(len(self.get_s().filter(F(tag='awesome') | F(tag='boat') |
                                     F(tag='boring'))), 5)
        eq_(len(self.get_s().filter(or_={'foo': 'bar',
                                          'or_': {'tag': 'boat',
                                                  'width': '5'}
                                          })), 3)

    def test_filter_complicated(self):
        eq_(len(self.get_s().filter(F(tag='awesome', foo='bar') |
                                     F(tag='boring'))), 2)

    def test_filter_not(self):
        eq_(len(self.get_s().filter(~F(tag='awesome'))), 2)
        eq_(len(self.get_s().filter(~(F(tag='boring') | F(tag='boat')))), 3)
        eq_(len(self.get_s().filter(~F(tag='boat')).filter(~F(foo='bar'))), 3)
        eq_(len(self.get_s().filter(~F(tag='boat', foo='barf'))), 5)

    def test_filter_bad_field_action(self):
        with self.assertRaises(InvalidFieldActionError):
            len(self.get_s().filter(F(tag__faux='awesome')))

    def test_facet(self):
        qs = self.get_s().facet('tag')
        eq_(facet_counts_dict(qs, 'tag'), dict(awesome=3, boring=1, boat=1))

    def test_filtered_facet(self):
        qs = self.get_s().query(foo='car').filter(width=5)

        # filter doesn't apply to facets
        eq_(facet_counts_dict(qs.facet('tag'), 'tag'),
            {'awesome': 2})

        # filter does apply to facets
        eq_(facet_counts_dict(qs.facet('tag', filtered=True), 'tag'),
            {'awesome': 1})

    def test_global_facet(self):
        qs = self.get_s().query(foo='car').filter(width=5)

        # facet restricted to query
        eq_(facet_counts_dict(qs.facet('tag'), 'tag'),
            {'awesome': 2})

        # facet applies to all of corpus
        eq_(facet_counts_dict(qs.facet('tag', global_=True), 'tag'),
            dict(awesome=3, boring=1, boat=1))

    def test_facet_raw(self):
        qs = self.get_s().facet_raw(tags={'terms': {'field': 'tag'}})
        eq_(facet_counts_dict(qs, 'tags'),
            dict(awesome=3, boring=1, boat=1))

        qs = (self.get_s()
              .query(foo='car')
              .facet_raw(tags={'terms': {'field': 'tag'}}))
        eq_(facet_counts_dict(qs, 'tags'),
            {'awesome': 2})

    def test_facet_raw_overrides_facet(self):
        """facet_raw overrides facet with the same facet name."""
        qs = (self.get_s()
              .query(foo='car')
              .facet('tag')
              .facet_raw(tag={'terms': {'field': 'tag'}, 'global': True}))
        eq_(facet_counts_dict(qs, 'tag'),
            dict(awesome=3, boring=1, boat=1))

    def test_order_by(self):
        res = self.get_s().filter(tag='awesome').order_by('-width')
        eq_([d.id for d in res], [5, 3, 1])

    def test_repr(self):
        res = self.get_s()[:2]
        list_ = list(res)

        eq_(repr(list_), repr(res))

    def test_explain(self):
        qs = self.get_s().query(foo='car')

        assert 'explain' not in qs._build_query()

        qs = qs.explain(True)

        # You put the explain in...
        assert qs._build_query()['explain'] == True

        qs = qs.explain(False)

        # You take the explain out...
        assert 'explain' not in qs._build_query()

        # Shake it all about...
        qs = qs.explain(True)

        res = list(qs)
        assert res[0]._explanation


class ResultsTests(HasDataTestCase):
    def test_default_results_are_dicts(self):
        """With untyped S, return dicts."""
        searcher = list(S().indexes(self.index_name).query(foo='bar'))
        assert isinstance(searcher[0], dict)

    def test_typed_s_returns_type(self):
        """With typed S, return objects of type."""
        searcher = list(S(FakeModel).indexes(self.index_name).query(foo='bar'))
        assert isinstance(searcher[0], FakeModel)

    def test_values_dict_results(self):
        """With values_dict, return list of dicts."""
        searcher = list(self.get_s().query(foo='bar').values_dict())
        assert isinstance(searcher[0], dict)

    def test_values_list_results_no_fields(self):
        """No values_list fields, this returns a list of tuples."""
        searcher = list(self.get_s().query(foo='bar').values_list())
        eq_(searcher[0], (1,))

    def test_values_list_results(self):
        """With values_list fields, returns list of tuples."""
        searcher = list(self.get_s().query(foo='bar')
                                    .values_list('foo', 'width'))
        assert isinstance(searcher[0], tuple)

    def test_default_results_form_has_score(self):
        """Test default results form has _score."""
        searcher = list(self.get_s().query(foo='bar'))
        assert hasattr(searcher[0], '_score')

    def test_values_list_form_has_score(self):
        """Test default results form has _score."""
        searcher = list(self.get_s().query(foo='bar').values_list())
        assert hasattr(searcher[0], '_score')

    def test_values_dict_form_has_score(self):
        """Test default results form has _score."""
        searcher = list(self.get_s().query(foo='bar').values_dict())
        assert hasattr(searcher[0], '_score')

    def test_values_dict_no_args(self):
        """Calling values_dict() with no args fetches all fields."""
        eq_(S().query(fld1=2)
               .values_dict()
               ._build_query(),
            {"query": {"term": {"fld1": 2}}})

    def test_values_list_no_args(self):
        """Calling values() with no args fetches only id."""
        eq_(S(FakeModel).query(fld1=2)
                        .values_list()
                        ._build_query(),
            {'query':
                 {"term": {"fld1": 2}},
             'fields': ['id']})

    def test_values_dict_id(self):
        """Calling values_dict('id') shouldn't return the ID field twice."""
        eq_(S(FakeModel).query(fld1=2)
                        .values_dict('id')
                        ._build_query(),
            {'query':
                 {"term": {"fld1": 2}},
             'fields': ['id']})

    def test_values_list_id(self):
        """Calling values('id') shouldn't return the ID field twice."""
        eq_(S(FakeModel).query(fld1=2)
                        .values_list('id')
                        ._build_query(),
            {'query':
                 {"term": {"fld1": 2}},
             'fields': ['id']})

    def test_values_dict_implicit_id(self):
        """Calling values_dict() always fetches ID."""
        eq_(S(FakeModel).query(fld1=2)
                        .values_dict('thing')
                        ._build_query(),
            {'query':
                 {"term": {"fld1": 2}},
             'fields': ['thing', 'id']})

    def test_values_list_implicit_id(self):
        """Calling values() always fetches ID."""
        eq_(S(FakeModel).query(fld1=2)
                        .values_list('thing')
                        ._build_query(),
            {'query':
                 {"term": {"fld1": 2}},
             'fields': ['thing', 'id']})