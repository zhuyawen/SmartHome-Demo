# -*- coding: utf-8 -*-
"""
Utils for database usage.
"""
import functools
import inspect
import logging
import re
from sqlalchemy import or_
from DB import models, exception


def model_query(session, model):
    """model query."""
    if not issubclass(model, models.Base):
        raise exception.DatabaseException("model should be a subclass of BASE!")

    return session.query(model)


def _default_list_condition_func(col_attr, value, condition_func):
    conditions = []
    for sub_value in value:
        condition = condition_func(col_attr, sub_value)
        if condition is not None:
            conditions.append(condition)
    if conditions:
        return or_(*conditions)
    else:
        return None


def _one_item_list_condition_func(col_attr, value, condition_func):
    if value:
        return condition_func(col_attr, value[0])
    else:
        return None


def _model_filter_by_condition(
        query, col_attr, value, condition_func,
        list_condition_func=_default_list_condition_func):
    if isinstance(value, list):
        condition = list_condition_func(
            col_attr, value, condition_func
        )
    else:
        condition = condition_func(col_attr, value)
    if condition is not None:
        query = query.filter(condition)
    return query


def _between_condition(col_attr, value):
    if value[0] is not None and value[1] is not None:
        return col_attr.between(value[0], value[1])
    if value[0] is not None:
        return col_attr >= value[0]
    if value[1] is not None:
        return col_attr <= value[1]
    return None


def model_order_by(query, model, order_by):
    if not order_by:
        return query
    order_by_cols = []
    for key in order_by:
        if isinstance(key, tuple):
            key, is_desc = key
        else:
            is_desc = False
        if isinstance(key, basestring):
            if hasattr(model, key):
                col_attr = getattr(model, key)
            else:
                continue
        else:
            col_attr = key
        if is_desc:
            order_by_cols.append(col_attr.desc())
        else:
            order_by_cols.append(col_attr)
    return query.order_by(*order_by_cols)


def model_filter(query, model, **filters):
    for key, value in filters.items():
        if isinstance(key, basestring):
            if hasattr(model, key):
                col_attr = getattr(model, key)
            else:
                continue
        else:
            col_attr = key
        if isinstance(value, list):
            query = query.filter(col_attr.in_(value))
        elif isinstance(value, dict):
            if 'eq' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['eq'],
                    lambda attr, data: attr == data,
                    lambda attr, data, condition_func: attr.in_(data)
                )
            if 'lt' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['lt'],
                    lambda attr, data: attr < data,
                    _one_item_list_condition_func
                )
            if 'gt' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['gt'],
                    lambda attr, data: attr > data,
                    _one_item_list_condition_func
                )
            if 'le' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['le'],
                    lambda attr, data: attr <= data,
                    _one_item_list_condition_func
                )
            if 'ge' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['ge'],
                    lambda attr, data: attr >= data,
                    _one_item_list_condition_func
                )
            if 'ne' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['ne'], None,
                    lambda attr, data, condition_func: ~attr.in_(data)
                )
            if 'in' in value:
                query = query.filter(col_attr.in_(value['in']))
            if 'startswith' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['startswith'],
                    lambda attr, data: attr.like('%s%%' % data)
                )
            if 'endswith' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['endswith'],
                    lambda attr, data: attr.like('%%%s' % data)
                )
            if 'like' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['like'],
                    lambda attr, data: attr.like('%%%s%%' % data)
                )
            if 'between' in value:
                query = _model_filter_by_condition(
                    query, col_attr, value['between'],
                    _between_condition
                )
        else:
            query = query.filter(col_attr == value)

    return query


def replace_output(**output_mapping):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return _replace_output(
                func(*args, **kwargs), **output_mapping
            )
        return wrapper
    return decorator


def _replace_output(data, **output_mapping):
    """Helper to replace output data."""
    if isinstance(data, list):
        return [
            _replace_output(item, **output_mapping)
            for item in data
        ]
    info = {}
    for key, value in data.items():
        if key in output_mapping:
            output_key = output_mapping[key]
            if isinstance(output_key, basestring):
                info[output_key] = value
            else:
                info[key] = (
                    _replace_output(value, **output_key)
                )
        else:
            info[key] = value
    return info


def wrap_to_dict(support_keys=[], **filters):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return _wrapper_dict(
                func(*args, **kwargs), support_keys, **filters
            )
        return wrapper
    return decorator


def _wrapper_dict(data, support_keys, **filters):
    """Helper for warpping db object into dictionary."""
    if isinstance(data, list):
        return [
            _wrapper_dict(item, support_keys, **filters)
            for item in data
        ]
    if isinstance(data, models.HelperMixin):
        data = data.join_to_dict()
        # data = data.to_dict()
    if not data:
        return None
    if not isinstance(data, dict):
        raise exception.InvalidResponse(
            'response %s type is not dict' % data
        )
    info = {}
    for key in support_keys:
        if key in data:
            if key in filters:
                filter_keys = filters[key]
                if isinstance(filter_keys, dict):
                    info[key] = _wrapper_dict(
                        data[key], filter_keys.keys(),
                        **filter_keys
                    )
                else:
                    info[key] = _wrapper_dict(
                        data[key], filter_keys
                    )
            else:
                info[key] = data[key]
    return info


def replace_input_types(**kwarg_mapping):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            replaced_kwargs = {}
            for key, value in kwargs.items():
                if key in kwarg_mapping:
                    replaced_kwargs[key] = kwarg_mapping[key](value)
                else:
                    replaced_kwargs[key] = value
            return func(*args, **replaced_kwargs)
        return wrapper
    return decorator


def replace_filters(**filter_mapping):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **filters):
            replaced_filters = {}
            for key, value in filters.items():
                if key in filter_mapping:
                    replaced_filters[filter_mapping[key]] = value
                else:
                    replaced_filters[key] = value
            return func(*args, **replaced_filters)
        return wrapper
    return decorator


def supported_filters(
    support_keys=[],
    optional_support_keys=[],
    ignore_support_keys=[]
):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **filters):
            must_support_keys = set(support_keys)
            all_support_keys = must_support_keys | set(optional_support_keys)
            filter_keys = set(filters)
            unsupported_keys = (
                filter_keys - all_support_keys - set(ignore_support_keys)
            )
            if unsupported_keys:
                raise exception.InvalidParameter(
                    'filter keys %s are not supported' % str(
                        list(unsupported_keys)
                    )
                )
            missing_keys = must_support_keys - filter_keys
            if missing_keys:
                raise exception.InvalidParameter(
                    'filter keys %s not found' % str(
                        list(missing_keys)
                    )
                )
            filtered_filters = dict([
                (key, value)
                for key, value in filters.items()
                if key not in ignore_support_keys
            ])
            return func(*args, **filtered_filters)
        return wrapper
    return decorator


def _obj_equal(check, obj):
    if check == obj:
        return True
    if not issubclass(obj.__class__, check.__class__):
        return False
    if isinstance(obj, dict):
        return _dict_equal(check, obj)
    elif isinstance(obj, list):
        return _list_equal(check, obj)
    else:
        return False


def _list_equal(check_list, obj_list):
    return set(check_list).issubset(set(obj_list))


def _dict_equal(check_dict, obj_dict):
    for key, value in check_dict.items():
        if (
            key not in obj_dict or
            not _obj_equal(check_dict[key], obj_dict[key])
        ):
            return False
    return True


def general_filter_callback(general_filter, obj):
    if 'resp_eq' in general_filter:
        return _obj_equal(general_filter['resp_eq'], obj)
    elif 'resp_in' in general_filter:
        in_filters = general_filter['resp_in']
        if not in_filters:
            return True
        for in_filer in in_filters:
            if _obj_equal(in_filer, obj):
                return True
        return False
    elif 'resp_lt' in general_filter:
        return obj < general_filter['resp_lt']
    elif 'resp_le' in general_filter:
        return obj <= general_filter['resp_le']
    elif 'resp_gt' in general_filter:
        return obj > general_filter['resp_gt']
    elif 'resp_ge' in general_filter:
        return obj >= general_filter['resp_gt']
    elif 'resp_match' in general_filter:
        return bool(re.match(general_filter['resp_match'], obj))
    else:
        return True


def filter_output(filter_callbacks, filters, obj, missing_ok=False):
    for callback_key, callback_value in filter_callbacks.items():
        if callback_key not in filters:
            continue
        if callback_key not in obj:
            if missing_ok:
                continue
            else:
                raise exception.InvalidResponse(
                    '%s is not in %s' % (callback_key, obj)
                )
        if not callback_value(
            filters[callback_key], obj[callback_key]
        ):
            return False
    return True


def output_filters(missing_ok=False, **filter_callbacks):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **filters):
            filtered_obj_list = []
            obj_list = func(*args, **filters)
            for obj in obj_list:
                if filter_output(
                    filter_callbacks, filters, obj, missing_ok
                ):
                    filtered_obj_list.append(obj)
            return filtered_obj_list
        return wrapper
    return decorator


def _input_validates(args_validators, kwargs_validators, *args, **kwargs):
    for i, value in enumerate(args):
        if i < len(args_validators) and args_validators[i]:
            args_validators[i](value)
    for key, value in kwargs.items():
        if kwargs_validators.get(key):
            kwargs_validators[key](value)


def input_validates(*args_validators, **kwargs_validators):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _input_validates(
                args_validators, kwargs_validators,
                *args, **kwargs
            )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def _output_validates(kwargs_validators, obj):
    if isinstance(obj, list):
        for item in obj:
            _output_validates(kwargs_validators, item)
        return
    if isinstance(obj, models.HelperMixin):
        obj = obj.to_dict()
    if not isinstance(obj, dict):
        raise exception.InvalidResponse(
            'response %s type is not dict' % str(obj)
        )
    for key, value in obj.items():
        if key in kwargs_validators:
            kwargs_validators[key](value)


def output_validates(**kwargs_validators):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            obj = func(*args, **kwargs)
            if isinstance(obj, list):
                for obj_item in obj:
                    _output_validates(kwargs_validators, obj_item)
            else:
                _output_validates(kwargs_validators, obj)
            return obj
        return wrapper
    return decorator


def get_db_object(session, table, exception_when_missing=True, **kwargs):
    """Get db object."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s get db object %s from table %s',
            id(session), kwargs, table.__name__)
        db_object = model_filter(
            model_query(session, table), table, **kwargs
        ).first()
        logging.debug(
            'session %s got db object %s', id(session), db_object
        )
        if db_object:
            return db_object

        if not exception_when_missing:
            return None

        raise exception.RecordNotExists(
            'Cannot find the record in table %s: %s' % (
                table.__name__, kwargs
            )
        )


def add_db_object(session, table, exception_when_existing=True,
                  *args, **kwargs):
    """Create db object."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s add object %s atributes %s to table %s',
            id(session), args, kwargs, table.__name__)
        argspec = inspect.getargspec(table.__init__)
        arg_names = argspec.args[1:]
        arg_defaults = argspec.defaults
        if not arg_defaults:
            arg_defaults = []
        if not (
            len(arg_names) - len(arg_defaults) <= len(args) <= len(arg_names)
        ):
            raise exception.InvalidParameter(
                'arg names %s does not match arg values %s' % (
                    arg_names, args)
            )
        db_keys = dict(zip(arg_names, args))
        if db_keys:
            db_object = session.query(table).filter_by(**db_keys).first()
        else:
            db_object = None

        new_object = False
        if db_object:
            if exception_when_existing:
                raise exception.DuplicatedRecord(
                    '%s exists in table %s' % (db_keys, table.__name__)
                )
        else:
            db_object = table(**db_keys)
            new_object = True

        for key, value in kwargs.items():
            setattr(db_object, key, value)

        if new_object:
            session.add(db_object)
        session.flush()
        db_object.initialize()
        db_object.validate()
        logging.debug(
            'session %s db object %s added', id(session), db_object
        )
        return db_object


def list_db_objects(session, table, order_by=[], limit=None, **filters):
    """List db objects."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s list db objects by filters %s in table %s',
            id(session), filters, table.__name__
        )
        db_objects = model_order_by(
            model_filter(
                model_query(session, table),
                table,
                **filters
            ),
            table,
            order_by
        )
        if limit:
            if isinstance(limit, int):
                db_objects = db_objects.limit(limit)
        db_objects = db_objects.all()

        logging.debug(
            'session %s got listed db objects: %s',
            id(session), db_objects
        )
        return db_objects


def list_db_objects_by_group(session, table, select, group_by=None, **filters):
    """List db objects."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s list db objects by filters %s in table %s',
            id(session), filters, table.__name__
        )
        query = session.query(*select)
        db_objects = model_filter(query,
                                  table,
                                  **filters).group_by(group_by)
        db_objects = db_objects.all()
        print db_objects
        logging.debug(
            'session %s got listed db objects: %s',
            id(session), db_objects
        )
        return db_objects


def del_db_objects(session, table, **filters):
    """delete db objects."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s delete db objects by filters %s in table %s',
            id(session), filters, table.__name__
        )
        query = model_filter(
            model_query(session, table), table, **filters
        )
        db_objects = query.all()
        query.delete(synchronize_session=False)
        logging.debug(
            'session %s db objects %s deleted', id(session), db_objects
        )
        return db_objects


def update_db_objects(session, table, **filters):
    """Update db objects."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s update db objects by filters %s in table %s',
            id(session), filters, table.__name__)
        db_objects = model_filter(
            model_query(session, table), table, **filters
        ).all()
        for db_object in db_objects:
            logging.debug('update db object %s', db_object)
            session.flush()
            db_object.update()
            db_object.validate()
        logging.debug(
            'session %s db objects %s updated',
            id(session), db_objects
        )
        return db_objects


def update_db_object(session, db_object, **kwargs):
    """Update db object."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s update db object %s by value %s',
            id(session), db_object, kwargs
        )
        for key, value in kwargs.items():
            setattr(db_object, key, value)
        session.flush()
        db_object.update()
        db_object.validate()
        logging.debug(
            'session %s db object %s updated',
            id(session), db_object
        )
        return db_object


def del_db_object(session, db_object):
    """Delete db object."""
    with session.begin(subtransactions=True):
        logging.debug(
            'session %s delete db object %s',
            id(session), db_object
        )
        session.delete(db_object)
        logging.debug(
            'session %s db object %s deleted',
            id(session), db_object
        )
        return db_object