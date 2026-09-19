/// Fallback web storage implementation for non-web platforms (IO/desktop)
String? webStorageGet(String key) => null;
void webStorageSet(String key, String value) {}
void webStorageRemove(String key) {}
void webStorageClear() {}
