"""Configuration for production server"""
# noinspection PyUnresolvedReferences
from .prod import *  # noqa
import os

print os.environ

DEBUG = True

ALLOWED_HOSTS = ['*']

ADMINS = (
    ('Irwan Fathurrahman', 'irwan@kartoza.com'),)