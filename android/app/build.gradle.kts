plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.google.services)
}

// Build-time settings, from -P<name>=... or the environment (see docs/self-hosting.md):
//   hmd.applicationId     / HMD_APPLICATION_ID     package to install as (must match google-services.json)
//   hmd.defaultServerUrl  / HMD_SERVER_URL         server used when pairing by typed code (QR carries its own)
//   hmd.keystoreFile, hmd.keystorePassword, hmd.keyAlias, hmd.keyPassword
//                         / HMD_KEYSTORE_FILE, HMD_KEYSTORE_PASSWORD, HMD_KEY_ALIAS, HMD_KEY_PASSWORD
fun setting(property: String, env: String): String? =
    (findProperty(property) as String?)?.takeIf { it.isNotBlank() }
        ?: System.getenv(env)?.takeIf { it.isNotBlank() }

val hmdApplicationId = setting("hmd.applicationId", "HMD_APPLICATION_ID") ?: "com.notifs.app"
val hmdDefaultServerUrl = setting("hmd.defaultServerUrl", "HMD_SERVER_URL") ?: "https://hmd-api.duckdns.org"
val hmdKeystoreFile = setting("hmd.keystoreFile", "HMD_KEYSTORE_FILE")

android {
    namespace = "com.notifs.app"
    compileSdk = 35

    defaultConfig {
        applicationId = hmdApplicationId
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "0.2.1"

        buildConfigField("String", "DEFAULT_SERVER_URL", "\"${hmdDefaultServerUrl.trimEnd('/')}\"")

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        // Only when a keystore is configured; otherwise release builds stay unsigned
        // (Android Studio's "Generate Signed APK" signs them instead).
        if (hmdKeystoreFile != null) {
            create("release") {
                storeFile = file(hmdKeystoreFile)
                storePassword = setting("hmd.keystorePassword", "HMD_KEYSTORE_PASSWORD")
                keyAlias = setting("hmd.keyAlias", "HMD_KEY_ALIAS")
                keyPassword = setting("hmd.keyPassword", "HMD_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hmdKeystoreFile != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    implementation(libs.androidx.datastore.preferences)

    // Firebase
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging.ktx)

    // QR & Camera
    implementation(libs.camera.core)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    implementation(libs.barcode.scanning)

    // OkHttp
    implementation(libs.okhttp)

    // Unit Testing
    testImplementation("junit:junit:4.13.2")
}
