import os
import sys
import django

# Agregar tanto la raíz del proyecto como la carpeta apps al sys.path
sys.path.insert(0, os.path.abspath('../'))
sys.path.insert(0, os.path.abspath('../apps'))

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'GlobalExchange'
copyright = '2026, Equipo GlobalExchange'
author = 'Equipo GlobalExchange'
release = '1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

language = 'es'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']