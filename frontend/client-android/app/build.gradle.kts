import java.util.Properties
import org.openapitools.generator.gradle.plugin.tasks.GenerateTask

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.openapi.generator)
}

// Release signing (V2_SPEC §12.4): keystore.properties locally, OC_* variables in CI.
val signing = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}
fun secret(key: String, env: String): String? = signing.getProperty(key) ?: System.getenv(env)

// CI has no key yet (§12.7): -Poc.unsignedRelease=true builds an unsigned release APK.
// Without the flag and without a key, a release build fails instead of producing junk.
val unsignedRelease = providers.gradleProperty("oc.unsignedRelease").orNull == "true"

// API models generated from the committed contract-v2 export (P-14, build time only).
val openApiSpec = rootProject.file("../../backend/openapi/v2.json")
val generatedApi = layout.buildDirectory.dir("generated/openapi")
val generateApiModels by tasks.registering(GenerateTask::class) {
    generatorName.set("kotlin")
    inputSpec.set(openApiSpec.absolutePath)
    outputDir.set(generatedApi.get().asFile.absolutePath)
    modelPackage.set("com.bakingholic.orderchecker.api.model")
    globalProperties.set(mapOf("models" to "", "modelDocs" to "false", "modelTests" to "false"))
    configOptions.set(
        mapOf(
            "serializationLibrary" to "kotlinx_serialization",
            "enumPropertyNaming" to "UPPERCASE",
            "sourceFolder" to "src/main/kotlin",
            "dateLibrary" to "string",
        ),
    )
    // The export strips info.version on purpose (backend tests/test_openapi_exports.py).
    validateSpec.set(false)
    inputs.file(openApiSpec)
}

android {
    namespace = "com.bakingholic.orderchecker"
    // 37.2: the Compose BOM needs compile SDK >= 37.1. compileSdk only picks the APIs we can
    // call; runtime behaviour follows targetSdk.
    compileSdk {
        version = release(37) { minorApiLevel = 2 }
    }

    defaultConfig {
        applicationId = "com.bakingholic.orderchecker"
        minSdk = 30 // Android 11 (Newland MT67)
        targetSdk = 37
        versionCode = providers.gradleProperty("oc.versionCode").get().toInt()
        versionName = providers.gradleProperty("oc.versionName").get()
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // Stage-1 server (V2_SERVER_ADDRESS §4.2); -Poc.defaultServer=http://10.0.2.2:8000 for
        // an emulator rehearsal against a local backend.
        val defaultServer = providers.gradleProperty("oc.defaultServer").orElse("http://192.168.1.50:8000").get()
        buildConfigField("String", "DEFAULT_SERVER", "\"$defaultServer\"")
        // Hidden-settings PIN (P-13): from ~/.gradle/gradle.properties, -P or OC_SETTINGS_PIN;
        // never committed. Empty → the settings cannot be opened.
        val settingsPin = providers.gradleProperty("oc.settingsPin")
            .orElse(providers.environmentVariable("OC_SETTINGS_PIN")).orElse("").get()
        buildConfigField("String", "SETTINGS_PIN", "\"$settingsPin\"")
    }

    signingConfigs {
        create("release") {
            secret("storeFile", "OC_KEYSTORE_PATH")?.let { storeFile = file(it) }
            storePassword = secret("storePassword", "OC_KEYSTORE_PASSWORD")
            keyAlias = secret("keyAlias", "OC_KEY_ALIAS")
            keyPassword = secret("keyPassword", "OC_KEY_PASSWORD")
        }
    }

    buildTypes {
        release {
            signingConfig = if (unsignedRelease) null else signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        debug {
            applicationIdSuffix = ".debug" // installs beside the release app
            versionNameSuffix = "-debug"
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets["main"].kotlin.directories.add(generatedApi.get().dir("src/main/kotlin").asFile.path)

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    lint {
        warningsAsErrors = false
        abortOnError = true
        checkDependencies = false
    }
}

tasks.named("preBuild") { dependsOn(generateApiModels) }

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
}
