#!/usr/bin/env python3
"""Integrationstests gegen pretix 2026.8.0, SQLite und lokalen Mail-Ausgang.

Aufruf nach pip install pretix==2026.8.0 und pip install --no-deps -e runtime/termine-pretix/plugin:
python tests/run-pretix-tests.py
PostgreSQL-Advisory-Locks werden hier ersetzt; Parallelität bleibt ein NS8-Test.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DJANGO_SETTINGS_MODULE"] = "pretix.testutils.settings"

import django
from django.conf import settings

settings.DATABASES["default"]["NAME"] = ":memory:"
# Einheitlicher, schneller Testaufbau auch innerhalb von GitHub Actions.
settings.MIGRATION_MODULES = __import__("pretix.testutils.settings", fromlist=["DisableMigrations"]).DisableMigrations()
settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
django.setup()

from django.test.runner import DiscoverRunner

sys.exit(bool(DiscoverRunner(verbosity=2, interactive=False).run_tests(["pretix_regressions"])))
