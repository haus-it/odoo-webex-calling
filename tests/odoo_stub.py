# -*- coding: utf-8 -*-
"""Just enough of Odoo to import the modules outside Odoo.

WHY THIS EXISTS
The interesting logic in this addon is not Odoo-specific: which spelling of a
CDR column to read, how to turn "+49 5251 …" into the shapes a CRM might have
stored, how to slice a time range Cisco will accept. All of that can be
tested in a second, on any machine, without a database.

What this stub CANNOT test is Odoo itself - ORM behaviour, views, access
rules, the cron. Those need a real instance, and the README says so. A stub
that pretended otherwise would be worse than no tests at all.
"""

import sys
import types


def install():
    if "odoo" in sys.modules:
        return

    odoo = types.ModuleType("odoo")

    class _Field:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _Fields:
        Boolean = Char = Integer = Datetime = Date = Text = Selection = _Field
        Many2one = One2many = Many2many = Float = Binary = _Field

        @staticmethod
        def now():
            import datetime

            return datetime.datetime.utcnow()

    class _Models:
        class Model:
            _name = ""

            def __init_subclass__(cls, **kwargs):
                super().__init_subclass__(**kwargs)

    class _Api:
        @staticmethod
        def model(func):
            return func

        @staticmethod
        def depends(*args):
            def wrap(func):
                return func

            return wrap

    class _Exceptions:
        class UserError(Exception):
            pass

        class ValidationError(Exception):
            pass

    odoo.fields = _Fields
    odoo.models = _Models
    odoo.api = _Api
    odoo.exceptions = _Exceptions
    odoo._ = lambda text, *a, **kw: text

    http = types.ModuleType("odoo.http")
    http.request = None

    class _Controller:
        pass

    http.Controller = _Controller
    http.route = lambda *a, **kw: (lambda f: f)
    odoo.http = http

    sys.modules["odoo"] = odoo
    sys.modules["odoo.http"] = http
    sys.modules["odoo.exceptions"] = types.SimpleNamespace(
        UserError=_Exceptions.UserError, ValidationError=_Exceptions.ValidationError)
