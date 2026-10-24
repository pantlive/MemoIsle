# 原生 JNI 按完整类名、字段名读取语音配置，必须保留 SDK 的接口结构。
-keep class com.k2fsa.sherpa.onnx.** { *; }

# Room 通过反射调用生成数据库的无参构造方法，启动 WorkManager 时就会用到。
# 只保留类名不足以阻止 R8 删除构造方法，会导致应用在登录页出现前闪退。
-keep class * extends androidx.room.RoomDatabase {
    public <init>();
}

# WorkManager 持久化 Worker 类名，保留名称和构造方法以兼容已排队任务。
-keep,allowoptimization class com.memoisle.app.sync.MemoSyncWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}
