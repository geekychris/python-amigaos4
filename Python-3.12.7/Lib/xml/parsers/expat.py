"""Interface to the Expat non-validating XML parser."""
import sys

try:
    from pyexpat import *

    # provide pyexpat submodules as xml.parsers.expat submodules
    sys.modules['xml.parsers.expat.model'] = model
    sys.modules['xml.parsers.expat.errors'] = errors
except ImportError:
    raise ImportError("pyexpat module is not available")
