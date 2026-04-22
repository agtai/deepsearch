# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
import binascii

from fastapi import status

from server.deepsearch.common.exception.exceptions import (
    ReportConvertBasicException,
    ReportConvertExecutionException,
    ReportConvertValidationException,
)
from server.schemas.report import ReportConvertReq, ReportConvertRes


def _raise_report_convert_error(
        exc_cls: type[ReportConvertBasicException],
        detail: str,
        cause: Exception | None = None,
) -> None:
    """Raise a report convert exception and preserve the original cause.

    Args:
        exc_cls: 需要抛出的报告导出异常类型。
        detail: 暴露给上层的错误信息。
        cause: 原始异常，可选。

    Raises:
        ReportConvertBasicException: 指定类型的业务异常。
    """
    exc = exc_cls(detail)
    if cause is not None:
        raise exc from cause
    raise exc


def report_convert(req: ReportConvertReq) -> ReportConvertRes:
    """Convert a final_result payload into an export bundle.

    Args:
        req: 报告导出请求，包含 final_result 和目标格式。

    Returns:
        ReportConvertRes: 包含 ZIP 压缩包 base64 内容的响应对象。

    Raises:
        ReportConvertValidationException: final_result 中的 base64 或文本内容非法。
        ReportConvertExecutionException: 导出流程执行失败。
    """
    processor = req.convert_type.get_processor()
    try:
        b64_convert_content = processor.convert_from_final_result_to_bundle_base64(req.final_result)
    except ReportConvertBasicException:
        raise
    except binascii.Error as exc:
        _raise_report_convert_error(ReportConvertValidationException, "invalid Base64 string", exc)
    except UnicodeDecodeError as exc:
        _raise_report_convert_error(ReportConvertValidationException, "not valid UTF-8 text", exc)
    except Exception as exc:
        _raise_report_convert_error(ReportConvertExecutionException, "convert failed", exc)

    if not b64_convert_content:
        _raise_report_convert_error(ReportConvertExecutionException, "convert failed")

    return ReportConvertRes(
        code=status.HTTP_200_OK,
        msg='success',
        convert_content=b64_convert_content
    )
