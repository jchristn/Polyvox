"""Errors shared by CLI, isolated jobs, and HTTP."""


class TranscriberError(Exception):
    code = "transcription_failed"
    status = 500


class ConfigurationError(TranscriberError):
    code = "configuration_error"
    status = 503


class InvalidMedia(TranscriberError):
    code = "invalid_media"
    status = 422


class Busy(TranscriberError):
    code = "busy"
    status = 503


class BackendFailure(TranscriberError):
    code = "backend_failure"
    status = 503


class JobTimeout(TranscriberError):
    code = "timeout"
    status = 504


ERROR_TYPES = {
    cls.code: cls
    for cls in (
        TranscriberError,
        ConfigurationError,
        InvalidMedia,
        Busy,
        BackendFailure,
        JobTimeout,
    )
}
