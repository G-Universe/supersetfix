# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import json
import base64
import logging
import requests
from dataclasses import dataclass
from typing import Any, Optional

import nh3
from flask_babel import gettext as __

from superset import app
from superset.exceptions import SupersetErrorsException
from superset.reports.models import ReportRecipientType
from superset.reports.notifications.base import BaseNotification
from superset.reports.notifications.exceptions import NotificationError
from superset.utils.core import HeaderDataType
from superset.utils.decorators import statsd_gauge

logger = logging.getLogger(__name__)


@dataclass
class WebhookContent:
    body: str
    header_data: Optional[HeaderDataType] = None
    data: Optional[dict[str, Any]] = None
    images: Optional[list[str, bytes]] = None


class WebhookNotification(BaseNotification):  # pylint: disable=too-few-public-methods
    """
    Sends a webhook notification for a report recipient
    """

    type = ReportRecipientType.WEBHOOK

    def _error_template(self, text: str) -> str:
        return __(
            """
            Your report/alert was unable to be generated because of the following error: %(text)s
            Please check your dashboard/chart for errors.
            "%(url)s"
            """,
            text=text,
            url=self._content.url,
        )

    def _get_content(self) -> WebhookContent:
        if self._content.text:
            return WebhookContent(body=self._error_template(self._content.text))

        images = []

        if self._content.screenshots:
            images = [
                base64.b64encode(screenshot).decode('ascii')
                for screenshot in self._content.screenshots
            ]

        # Strip any malicious HTML from the description
        # pylint: disable=no-member
        description = nh3.clean(
            self._content.description or "",
        )

        body = {
            'description': description,
            'url': self._content.url
        }
        csv_data = None
        if self._content.csv:
            csv_data = {__("%(name)s.csv", name=self._content.name): self._content.csv}

        return WebhookContent(
            body=body,
            images=images,
            data=csv_data,
            header_data=self._content.header_data,
        )

    def _get_subject(self) -> str:
        return __(
            "%(title)s",
            title=self._content.name,
        )

    def _get_to(self) -> str:
        return json.loads(self._recipient.recipient_config_json)["target"]

    @statsd_gauge("reports.email.send")
    def send(self) -> None:
        subject = self._get_subject()
        content = self._get_content()
        to = self._get_to()
        
        payload = {
            'subject': subject,
            'content': {
                'body': content.body,
                'data': content.data,
                'images': content.images,
            }
        }

        try:
            response = requests.post(to, headers={}, data=json.dumps(payload), timeout=30)
            response.raise_for_status()
            logger.info("Report sent to webhook, notification content is %s, url:%s, status scode:%d", content.header_data, to, response.status_code)
        except SupersetErrorsException as ex:
            raise NotificationError(
                ";".join([error.message for error in ex.errors])
            ) from ex
        except Exception as ex:
            raise NotificationError(str(ex)) from ex
