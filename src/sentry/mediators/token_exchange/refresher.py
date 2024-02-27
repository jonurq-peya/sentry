from django.db import router

from sentry import analytics
from sentry.coreapi import APIUnauthorized
from sentry.mediators.mediator import Mediator
from sentry.mediators.param import Param
from sentry.mediators.token_exchange.util import token_expiration
from sentry.mediators.token_exchange.validator import Validator
from sentry.models.apiapplication import ApiApplication
from sentry.models.apitoken import ApiToken
from sentry.models.integrations.sentry_app import SentryApp
from sentry.models.integrations.sentry_app_installation import SentryAppInstallation
from sentry.models.user import User
from sentry.services.hybrid_cloud.app import RpcSentryAppInstallation
from sentry.types.token import AuthTokenType
from sentry.utils.cache import memoize


class Refresher(Mediator):
    """
    Exchanges a Refresh Token for a new Access Token
    """

    install = Param(RpcSentryAppInstallation)
    refresh_token = Param(str)
    client_id = Param(str)
    user = Param(User)
    using = router.db_for_write(User)

    def call(self):
        self._validate()
        self._delete_token()
        return self._create_new_token()

    def record_analytics(self):
        analytics.record(
            "sentry_app.token_exchanged",
            sentry_app_installation_id=self.install.id,
            exchange_type="refresh",
        )

    def _validate(self):
        Validator.run(install=self.install, client_id=self.client_id, user=self.user)

        self._validate_token_belongs_to_app()

    def _validate_token_belongs_to_app(self):
        if self.token.application != self.application:
            raise APIUnauthorized

    def _delete_token(self):
        self.token.delete()

    def _create_new_token(self):
        token = ApiToken.objects.create(
            user=self.user,
            application=self.application,
            scope_list=self.sentry_app.scope_list,
            expires_at=token_expiration(),
            token_type=AuthTokenType.INTEGRATION,
        )
        try:
            SentryAppInstallation.objects.get(id=self.install.id).update(api_token=token)
        except SentryAppInstallation.DoesNotExist:
            pass
        return token

    @memoize
    def token(self):
        try:
            return ApiToken.objects.get(refresh_token=self.refresh_token)
        except ApiToken.DoesNotExist:
            raise APIUnauthorized

    @memoize
    def application(self):
        try:
            return ApiApplication.objects.get(client_id=self.client_id)
        except ApiApplication.DoesNotExist:
            raise APIUnauthorized

    @property
    def sentry_app(self):
        try:
            return self.application.sentry_app
        except SentryApp.DoesNotExist:
            raise APIUnauthorized
