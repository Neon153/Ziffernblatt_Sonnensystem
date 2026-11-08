plugins {
    alias(libs.plugins.android.application)
}

android {
    // Watch Face Format: no code at all, only resources
    enableKotlin = false
    namespace = "com.neon153.sonnensystem"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.neon153.sonnensystem"
        // WFF version 4 needs Wear OS 6 (API 36)
        minSdk = 36
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        debug {
            isMinifyEnabled = true
        }
        release {
            isMinifyEnabled = true
            // must stay false, otherwise the resources referenced only from watchface.xml get stripped
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}
