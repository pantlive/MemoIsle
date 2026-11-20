import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

val releaseApiBaseUrl = providers.gradleProperty("MEMOISLE_API_BASE_URL")
    .orElse("https://memo.17115859.xyz:9443/api/v1/")
val senseVoiceModelArchiveUrl = providers.gradleProperty("MEMOISLE_SENSEVOICE_MODEL_URL")
    .orElse(
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/" +
            "asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2",
    )

val sherpaOnnxVersion = "1.13.7"
// 官方 AAR 的 SHA-256；升级 sherpaOnnxVersion 时一起更新，下载内容对不上就报错，不会用到坏包。
val sherpaOnnxSha256 = "c4ef49e309f24fcee5c106b8a279481aaecaabb078cd37b2cd6e9a62cc8a73c8"
val sherpaOnnxAar = layout.buildDirectory.file(
    "third-party/sherpa-onnx-$sherpaOnnxVersion.aar",
)
// 49MB 的 AAR 放在 Gradle 用户目录里各 worktree、各次 clean 共用，只下载一次；
// 以前放在 build 目录，每个新 worktree 都要从 GitHub 重新下载，网络慢时一次要一个多小时。
val sherpaOnnxSharedAar = gradle.gradleUserHomeDir.resolve(
    "caches/memoisle-third-party/sherpa-onnx-$sherpaOnnxVersion.aar",
)
val downloadSherpaOnnxAar by tasks.registering {
    // 任务动作只捕获局部变量，避免把 Gradle 脚本对象写进配置缓存。
    val aarTarget = sherpaOnnxAar
    val aarVersion = sherpaOnnxVersion
    val aarSha256 = sherpaOnnxSha256
    val sharedAar = sherpaOnnxSharedAar
    outputs.file(aarTarget)
    doLast {
        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        fun isValid(file: File): Boolean = file.isFile && sha256(file) == aarSha256

        val destination = aarTarget.get().asFile
        if (isValid(destination)) {
            return@doLast
        }
        if (!isValid(sharedAar)) {
            sharedAar.parentFile.mkdirs()
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
            // 先写临时文件，校验通过再原子改名：下载中断或几个构建同时下载都不会留下半截文件被当成好包。
            val partial = File.createTempFile("sherpa-onnx-$aarVersion-", ".part", sharedAar.parentFile)
            try {
                connection.apply {
                    connectTimeout = 30_000
                    readTimeout = 120_000
                }.getInputStream().use { input ->
                    partial.outputStream().use { output -> input.copyTo(output) }
                }
                val actual = sha256(partial)
                if (actual != aarSha256) {
                    throw GradleException(
                        "sherpa-onnx $aarVersion AAR 校验失败：期望 $aarSha256，实际 $actual（$downloadUrl）",
                    )
                }
                Files.move(
                    partial.toPath(),
                    sharedAar.toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE,
                )
            } finally {
                partial.delete()
            }
        }
        destination.parentFile.mkdirs()
        val staged = File.createTempFile("sherpa-onnx-$aarVersion-", ".part", destination.parentFile)
        try {
            sharedAar.copyTo(staged, overwrite = true)
            Files.move(staged.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING)
        } finally {
            staged.delete()
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
        versionCode = 6
        versionName = "0.1.5"
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
            // 发布包覆盖 ARM 手机，模拟器架构保留在 Debug 中。
            ndk {
                abiFilters += listOf("arm64-v8a", "armeabi-v7a")
            }
            isMinifyEnabled = true
            isShrinkResources = true
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
        // 压缩原生库降低下载体积，由 Android 安装时按设备架构解压。
        jniLibs.useLegacyPackaging = true
    }
}

dependencies {
    // sherpa-onnx 官方 AAR 下载到 Gradle 用户目录共用、再拷进构建目录，不把 40MB 以上的二进制提交到仓库。
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
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")

    testImplementation("junit:junit:4.13.2")
    // 单元测试跑在 JVM 上，没有 Android 自带的 org.json，需要单独引入。
    testImplementation("org.json:json:20240303")

    debugImplementation("androidx.compose.ui:ui-test-manifest")
    debugImplementation("androidx.compose.ui:ui-tooling")
}

// Android Gradle Plugin 的变体任务不会自动依赖文件下载任务，需要显式串起来。
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(downloadSherpaOnnxAar)
}
