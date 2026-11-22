# kotlinx.serialization ships its own consumer rules; keep generated API models' serializers.
-keep,includedescriptorclasses class com.bakingholic.orderchecker.api.model.**$$serializer { *; }
-keepclassmembers class com.bakingholic.orderchecker.api.model.** {
    *** Companion;
}
