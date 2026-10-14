<!--
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <cv-grid fullWidth>
    <cv-row>
      <cv-column class="page-title">
        <h2>{{ $t("settings.title") }}</h2>
      </cv-column>
    </cv-row>
    <cv-row v-if="error.getConfiguration">
      <cv-column>
        <NsInlineNotification
          kind="error"
          :title="$t('action.get-configuration')"
          :description="error.getConfiguration"
          :showCloseButton="false"
        />
      </cv-column>
    </cv-row>
    <!-- Adresse und Mailversand -->
    <cv-row>
      <cv-column>
        <cv-tile light>
          <cv-form @submit.prevent="configureModule">
            <h4 class="mg-bottom-sm">{{ $t("settings.address_title") }}</h4>
            <cv-text-input
              :label="$t('settings.host')"
              placeholder="termine.example.org"
              v-model.trim="host"
              class="mg-bottom"
              :invalid-message="$t(error.host)"
              :disabled="busy"
              ref="host"
            />
            <cv-toggle
              value="letsEncrypt"
              :label="$t('settings.lets_encrypt')"
              v-model="isLetsEncryptEnabled"
              :disabled="busy"
              class="mg-bottom"
            >
              <template slot="text-left">{{ $t("settings.disabled") }}</template>
              <template slot="text-right">{{ $t("settings.enabled") }}</template>
            </cv-toggle>
            <cv-toggle
              value="httpToHttps"
              :label="$t('settings.http_to_https')"
              v-model="isHttpToHttpsEnabled"
              :disabled="busy"
              class="mg-bottom"
            >
              <template slot="text-left">{{ $t("settings.disabled") }}</template>
              <template slot="text-right">{{ $t("settings.enabled") }}</template>
            </cv-toggle>

            <h4 class="mg-bottom-sm">{{ $t("settings.mail_title") }}</h4>
            <cv-radio-group
              :label="$t('settings.mail_mode')"
              vertical
              class="mg-bottom"
            >
              <cv-radio-button
                name="mail_mode"
                :label="$t('settings.mail_smarthost')"
                value="smarthost"
                v-model="mailMode"
                :disabled="busy"
              />
              <cv-radio-button
                name="mail_mode"
                :label="$t('settings.mail_external')"
                value="external"
                v-model="mailMode"
                :disabled="busy"
              />
            </cv-radio-group>
            <NsInlineNotification
              v-if="mailMode === 'smarthost' && !smarthostAvailable"
              kind="warning"
              :title="$t('settings.no_smarthost_title')"
              :description="$t('settings.no_smarthost_description')"
              :showCloseButton="false"
            />
            <p
              v-if="mailMode === 'smarthost' && smarthostAvailable"
              class="mg-bottom helper"
            >
              {{ $t("settings.smarthost_used", { host: smarthostHost }) }}
            </p>
            <template v-if="mailMode === 'external'">
              <div class="smtp-grid mg-bottom">
                <cv-text-input
                  :label="$t('settings.smtp_host')"
                  placeholder="smtp.example.org"
                  v-model.trim="smtp.host"
                  :invalid-message="$t(error.smtp_host)"
                  :disabled="busy"
                  ref="smtp_host"
                />
                <cv-text-input
                  :label="$t('settings.smtp_port')"
                  v-model.trim="smtp.port"
                  type="number"
                  :invalid-message="$t(error.smtp_port)"
                  :disabled="busy"
                  ref="smtp_port"
                />
                <cv-dropdown
                  :label="$t('settings.smtp_encryption')"
                  v-model="smtp.encryption"
                  :disabled="busy"
                >
                  <cv-dropdown-item value="starttls">STARTTLS</cv-dropdown-item>
                  <cv-dropdown-item value="tls">SSL/TLS</cv-dropdown-item>
                  <cv-dropdown-item value="none">{{
                    $t("settings.smtp_no_encryption")
                  }}</cv-dropdown-item>
                </cv-dropdown>
                <cv-text-input
                  :label="$t('settings.smtp_username')"
                  v-model.trim="smtp.username"
                  autocomplete="off"
                  :disabled="busy"
                />
                <cv-text-input
                  :label="$t('settings.smtp_password')"
                  :helper-text="
                    smtpPasswordSet ? $t('settings.smtp_password_keep') : ''
                  "
                  v-model="smtp.password"
                  type="password"
                  autocomplete="new-password"
                  :disabled="busy"
                />
              </div>
            </template>
            <cv-text-input
              :label="$t('settings.mail_from')"
              :helper-text="$t('settings.mail_from_helper')"
              :placeholder="host ? 'no-reply@' + host : ''"
              v-model.trim="mailFrom"
              :invalid-message="$t(error.mail_from)"
              :disabled="busy"
              class="mg-bottom"
              ref="mail_from"
            />
            <NsInlineNotification
              v-if="error.configureModule"
              kind="error"
              :title="$t('action.configure-module')"
              :description="error.configureModule"
              :showCloseButton="false"
            />
            <NsButton
              kind="primary"
              :icon="Save20"
              :loading="loading.configureModule"
              :disabled="busy"
              >{{ $t("settings.save") }}</NsButton
            >
          </cv-form>
        </cv-tile>
      </cv-column>
    </cv-row>

    <!-- Konten -->
    <cv-row v-if="admins.length || mitarbeiter.length">
      <cv-column>
        <cv-tile light>
          <h4 class="mg-bottom-sm">{{ $t("settings.accounts_title") }}</h4>
          <p class="mg-bottom helper">
            {{ $t("settings.accounts_description") }}
            <a v-if="controlUrl" :href="controlUrl" target="_blank" rel="noopener">{{
              controlUrl
            }}</a>
          </p>
          <NsInlineNotification
            v-if="error.resetPasswords"
            kind="error"
            :title="$t('action.reset-passwords')"
            :description="error.resetPasswords"
            :showCloseButton="false"
          />
          <div
            v-for="gruppe in gruppen"
            :key="gruppe.key"
            class="mg-bottom"
          >
            <h5 class="mg-bottom-sm">{{ $t(gruppe.title) }}</h5>
            <table class="bx--data-table bx--data-table--compact konten">
              <thead>
                <tr>
                  <th>{{ $t("settings.login") }}</th>
                  <th>{{ $t("settings.name") }}</th>
                  <th>{{ $t("settings.password") }}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="konto in gruppe.konten" :key="konto.login">
                  <td class="mono">{{ konto.login }}</td>
                  <td>{{ konto.name }}</td>
                  <td class="mono">
                    {{ sichtbar[konto.login] ? konto.passwort : "••••••••••••" }}
                  </td>
                  <td class="aktionen">
                    <NsButton
                      kind="ghost"
                      size="small"
                      :icon="sichtbar[konto.login] ? ViewOff20 : View20"
                      @click="umschalten(konto.login)"
                      >{{
                        sichtbar[konto.login]
                          ? $t("settings.hide")
                          : $t("settings.show")
                      }}</NsButton
                    >
                    <NsButton
                      kind="ghost"
                      size="small"
                      :icon="Copy20"
                      @click="kopieren(konto)"
                      >{{
                        kopiert === konto.login
                          ? $t("settings.copied")
                          : $t("settings.copy")
                      }}</NsButton
                    >
                    <NsButton
                      kind="ghost"
                      size="small"
                      :icon="Renew20"
                      :loading="loading.resetPasswords === konto.login"
                      :disabled="!!loading.resetPasswords"
                      @click="resetPasswords(konto.login)"
                      >{{ $t("settings.regenerate") }}</NsButton
                    >
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <NsButton
            kind="secondary"
            :icon="Renew20"
            :loading="loading.resetPasswords === '*'"
            :disabled="!!loading.resetPasswords"
            @click="resetPasswords(null)"
            >{{ $t("settings.regenerate_all") }}</NsButton
          >
        </cv-tile>
      </cv-column>
    </cv-row>
  </cv-grid>
</template>

<script>
import to from "await-to-js";
import { mapState } from "vuex";
import {
  QueryParamService,
  UtilService,
  TaskService,
  IconService,
  PageTitleService,
} from "@nethserver/ns8-ui-lib";
import Copy20 from "@carbon/icons-vue/es/copy/20";
import Renew20 from "@carbon/icons-vue/es/renew/20";
import View20 from "@carbon/icons-vue/es/view/20";
import ViewOff20 from "@carbon/icons-vue/es/view--off/20";

export default {
  name: "Settings",
  mixins: [
    TaskService,
    IconService,
    UtilService,
    QueryParamService,
    PageTitleService,
  ],
  pageTitle() {
    return this.$t("settings.title") + " - " + this.appName;
  },
  data() {
    return {
      q: { page: "settings" },
      urlCheckInterval: null,
      Copy20,
      Renew20,
      View20,
      ViewOff20,
      host: "",
      isLetsEncryptEnabled: false,
      isHttpToHttpsEnabled: true,
      mailMode: "smarthost",
      mailFrom: "",
      smtp: { host: "", port: "587", username: "", password: "", encryption: "starttls" },
      smtpPasswordSet: false,
      smarthostAvailable: false,
      smarthostHost: "",
      admins: [],
      mitarbeiter: [],
      controlUrl: "",
      sichtbar: {},
      kopiert: "",
      loading: {
        getConfiguration: false,
        configureModule: false,
        resetPasswords: "",
      },
      error: {
        getConfiguration: "",
        configureModule: "",
        resetPasswords: "",
        host: "",
        lets_encrypt: "",
        http2https: "",
        mail_mode: "",
        mail_from: "",
        smtp_host: "",
        smtp_port: "",
        smtp_encryption: "",
      },
    };
  },
  computed: {
    ...mapState(["instanceName", "core", "appName"]),
    busy() {
      return this.loading.getConfiguration || this.loading.configureModule;
    },
    gruppen() {
      return [
        { key: "admins", title: "settings.admins", konten: this.admins },
        { key: "mitarbeiter", title: "settings.staff", konten: this.mitarbeiter },
      ];
    },
  },
  created() {
    this.getConfiguration();
  },
  beforeRouteEnter(to, from, next) {
    next((vm) => {
      vm.watchQueryData(vm);
      vm.urlCheckInterval = vm.initUrlBindingForApp(vm, vm.q.page);
    });
  },
  beforeRouteLeave(to, from, next) {
    clearInterval(this.urlCheckInterval);
    next();
  },
  methods: {
    // Start a module task and route its events to the given handlers
    async runTask(action, data, handlers, extra) {
      const eventId = this.getUuid();
      this.core.$root.$once(`${action}-aborted-${eventId}`, handlers.aborted);
      this.core.$root.$once(
        `${action}-completed-${eventId}`,
        handlers.completed
      );
      if (handlers.validationFailed) {
        this.core.$root.$once(
          `${action}-validation-failed-${eventId}`,
          handlers.validationFailed
        );
      }
      const res = await to(
        this.createModuleTaskForApp(this.instanceName, {
          action,
          data,
          extra: {
            title: this.$t("action." + action),
            isNotificationHidden: true,
            ...extra,
            eventId,
          },
        })
      );
      return res[0];
    },
    focusElement(ref) {
      const element = this.$refs[ref];
      if (element && element.focus) {
        element.focus();
      }
    },
    umschalten(login) {
      this.$set(this.sichtbar, login, !this.sichtbar[login]);
    },
    async kopieren(konto) {
      const [err] = await to(
        navigator.clipboard.writeText(`${konto.login}\t${konto.passwort}`)
      );
      if (!err) {
        this.kopiert = konto.login;
        setTimeout(() => (this.kopiert = ""), 2000);
      }
    },
    async getConfiguration() {
      this.loading.getConfiguration = true;
      this.error.getConfiguration = "";
      const err = await this.runTask("get-configuration", undefined, {
        aborted: this.getConfigurationAborted,
        completed: this.getConfigurationCompleted,
      });
      if (err) {
        console.error("error creating task get-configuration", err);
        this.error.getConfiguration = this.getErrorMessage(err);
        this.loading.getConfiguration = false;
      }
    },
    getConfigurationAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.getConfiguration = this.$t("error.generic_error");
      this.loading.getConfiguration = false;
    },
    getConfigurationCompleted(taskContext, taskResult) {
      const config = taskResult.output;
      this.host = config.host;
      this.isLetsEncryptEnabled = config.lets_encrypt;
      this.isHttpToHttpsEnabled = config.http2https;
      this.mailMode = config.mail_mode;
      this.mailFrom = config.mail_from || "";
      this.smtp = {
        host: config.smtp.host || "",
        port: String(config.smtp.port || 587),
        username: config.smtp.username || "",
        password: "",
        encryption: config.smtp.encryption || "starttls",
      };
      this.smtpPasswordSet = !!config.smtp.password_set;
      this.smarthostAvailable = !!config.smarthost_available;
      this.smarthostHost = config.smarthost_host || "";
      this.admins = config.admins || [];
      this.mitarbeiter = config.mitarbeiter || [];
      this.controlUrl = config.control_url || "";
      this.loading.getConfiguration = false;
      this.$nextTick(() => this.focusElement("host"));
    },
    validateConfigureModule() {
      this.clearErrors(this);
      let firstInvalid = "";
      if (!this.host) {
        this.error.host = "common.required";
        firstInvalid = firstInvalid || "host";
      }
      if (this.mailMode === "external") {
        if (!this.smtp.host) {
          this.error.smtp_host = "common.required";
          firstInvalid = firstInvalid || "smtp_host";
        }
        const port = Number(this.smtp.port);
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          this.error.smtp_port = "settings.invalid_smtp_port";
          firstInvalid = firstInvalid || "smtp_port";
        }
      }
      if (this.mailFrom && !/^[^@\s]+@[^@\s]+$/.test(this.mailFrom)) {
        this.error.mail_from = "settings.invalid_mail_from";
        firstInvalid = firstInvalid || "mail_from";
      }
      if (firstInvalid) {
        this.$nextTick(() => this.focusElement(firstInvalid));
        return false;
      }
      return true;
    },
    async configureModule() {
      if (!this.validateConfigureModule()) {
        return;
      }
      this.loading.configureModule = true;
      const data = {
        host: this.host,
        lets_encrypt: this.isLetsEncryptEnabled,
        http2https: this.isHttpToHttpsEnabled,
        mail_mode: this.mailMode,
        mail_from: this.mailFrom,
      };
      if (this.mailMode === "external") {
        data.smtp = {
          host: this.smtp.host,
          port: Number(this.smtp.port),
          username: this.smtp.username,
          password: this.smtp.password,
          encryption: this.smtp.encryption,
        };
      }
      const err = await this.runTask(
        "configure-module",
        data,
        {
          aborted: this.configureModuleAborted,
          completed: this.configureModuleCompleted,
          validationFailed: this.configureModuleValidationFailed,
        },
        {
          title: this.$t("settings.instance_configuration", {
            instance: this.instanceName,
          }),
          description: this.$t("settings.configuring"),
          isNotificationHidden: false,
        }
      );
      if (err) {
        console.error("error creating task configure-module", err);
        this.error.configureModule = this.getErrorMessage(err);
        this.loading.configureModule = false;
      }
    },
    configureModuleValidationFailed(validationErrors) {
      this.loading.configureModule = false;
      let firstInvalid = "";
      for (const validationError of validationErrors) {
        const param = validationError.parameter;
        this.error[param] = "settings." + validationError.error;
        firstInvalid = firstInvalid || param;
      }
      if (firstInvalid) {
        this.$nextTick(() => this.focusElement(firstInvalid));
      }
    },
    configureModuleAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.configureModule = this.$t("error.generic_error");
      this.loading.configureModule = false;
    },
    configureModuleCompleted() {
      this.loading.configureModule = false;
      this.getConfiguration();
    },
    async resetPasswords(login) {
      const frage = login
        ? this.$t("settings.confirm_regenerate", { login })
        : this.$t("settings.confirm_regenerate_all");
      if (!window.confirm(frage)) {
        return;
      }
      this.loading.resetPasswords = login || "*";
      this.error.resetPasswords = "";
      const err = await this.runTask(
        "reset-passwords",
        login ? { login } : {},
        {
          aborted: this.resetPasswordsAborted,
          completed: this.resetPasswordsCompleted,
          validationFailed: this.resetPasswordsAborted,
        },
        {
          title: this.$t("settings.regenerating", {
            instance: this.instanceName,
          }),
          isNotificationHidden: false,
        }
      );
      if (err) {
        console.error("error creating task reset-passwords", err);
        this.error.resetPasswords = this.getErrorMessage(err);
        this.loading.resetPasswords = "";
      }
    },
    resetPasswordsAborted(taskResult, taskContext) {
      console.error("reset-passwords aborted", taskResult, taskContext);
      this.error.resetPasswords = this.$t("error.generic_error");
      this.loading.resetPasswords = "";
    },
    resetPasswordsCompleted() {
      this.loading.resetPasswords = "";
      this.getConfiguration();
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";

.mg-bottom {
  margin-bottom: $spacing-06;
}

.mg-bottom-sm {
  margin-bottom: $spacing-03;
}

.helper {
  max-width: 44rem;
}

.smtp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: $spacing-05;
  align-items: end;
}

.konten {
  width: 100%;
}

.konten .mono {
  font-family: "IBM Plex Mono", monospace;
}

.konten .aktionen {
  white-space: nowrap;
  text-align: right;
}
</style>
