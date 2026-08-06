# pyexpat module stub for platforms without native expat XML library (e.g. AmigaOS 4)

class ExpatError(Exception):
    pass

error = ExpatError

class errors:
    XML_ERROR_NONE = 0

class model:
    pass

def ErrorString(code):
    return "Expat XML parser not built-in"

class _DummyParser:
    def __init__(self, encoding=None, namespace_separator=None):
        self.returns_unicode = True
        self.ordered_attributes = False
        self.specified_attributes = False
        self.CharacterDataHandler = None
        self.StartElementHandler = None
        self.EndElementHandler = None
        self.ProcessingInstructionHandler = None
        self.CommentHandler = None
        self.StartCdataSectionHandler = None
        self.EndCdataSectionHandler = None

    def SetParamEntityParsing(self, flag):
        return 0

    def Parse(self, data, isfinal=False):
        raise ExpatError("XML parsing requires pyexpat module")

    def ParseFile(self, file):
        raise ExpatError("XML parsing requires pyexpat module")

def ParserCreate(encoding=None, namespace_separator=None):
    return _DummyParser(encoding, namespace_separator)
