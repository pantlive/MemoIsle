import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

val releaseApiBaseUrl = providers.gradleProperty("MEMOISLE_API_BASE_URL")
    .orElse("https://api.example.invalid/api/v1/")
val senseVoiceModelArchiveUrl = providers.gradleProperty("MEMOISLE_SENSEVOICE_MODEL_URL")
    .orElse(
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/" +
            "asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2",
    )

val sherpaOnnxVersion = "1.13.7"
val sherpaOnnxAar = layout.buildDirectory.file(
    "third-party/sherpa-onnx-$sherpaOnnxVersion.aar",
)
val downloadSherpaOnnxAar by tasks.registering {
    // 任务动作只捕获局部变量，避免把 Gradle 脚本对象写进配置缓存。
    val aarTarget = sherpaOnnxAar
    val aarVersion = sherpaOnnxVersion
    outputs.file(aarTarget)
    doLast {
        val destination = aarTarget.get().asFile
        if (!destination.isFile || destination.length() < 1_000_000L) {
            destination.parentFile.mkdirs()
            val downloadUrl =
                "https://github.com/k2-fsa/sherpa-onnx/releases/download/" +
                    "v$aarVersion/sherpa-onnx-$aarVersion.aar"
            val proxy = runCatching {
                val proxyText = System.getenv("https_proxy")
                    ?: System.getenv("HTTPS_PROXY")
                    ?: System.getenv("http_proxy")
                    ?: System.getenv("HTTP_PROXY")
                    ?: return@runCatching null
                val proxyUri = URI(proxyText)
                val proxyHost = proxyUri.host ?: return@runCatching null
                val proxyPort = proxyUri.port.takeIf { it > 0 } ?: return@runCatching null
                val proxyType = if (proxyUri.scheme.startsWith("socks")) {
                    Proxy.Type.SOCKS
                } else {
                    Proxy.Type.HTTP
                }
                Proxy(proxyType, InetSocketAddress(proxyHost, proxyPort))
            }.getOrNull()
            val connection = if (proxy == null) {
                URI(downloadUrl).toURL().openConnection()
            } else {
                URI(downloadUrl).toURL().openConnection(proxy)
            }
            connection.apply {
                connectTimeout = 30_000
                readTimeout = 120_000
            }.getInputStream().use { input ->
                destination.outputStream().use { output -> input.copyTo(output) }
            }
        }
    }
}

android {
    namespace = "com.memoisle.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.memoisle.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField(
            "String",
            "SENSEVOICE_MODEL_ARCHIVE_URL",
            "\"${senseVoiceModelArchiveUrl.get()}\"",
        )

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"http://10.0.2.2:8000/api/v1/\"",
            )
        }
        release {
            isMinifyEnabled = false
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"${releaseApiBaseUrl.get()}\"",
            )
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
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

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    // sherpa-onnx 官方 AAR 在构建目录缓存，不把 40MB 以上的二进制提交到仓库。
    implementation(files(sherpaOnnxAar))
    implementation("org.apache.commons:commons-compress:1.27.1")
    implementation(platform("androidx.compose:compose-bom:2026.06.00"))
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.18.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.10.0")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")

    testImplementation("junit:junit:4.13.2")

    debugImplementation("androidx.compose.ui:ui-test-manifest")
    debugImplementation("androidx.compose.ui:ui-tooling")
}

// Android Gradle Plugin 的变体任务不会自动依赖文件下载任务，需要显式串起来。
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(downloadSherpaOnnxAar)
}
