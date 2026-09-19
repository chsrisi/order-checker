import 'dart:developer';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'safe_storage_io.dart' if (dart.library.js_interop) 'safe_storage_web.dart';

/// SafeStorage wraps FlutterSecureStorage to ensure that if the app is run
/// in an insecure context on the Web (plain HTTP via IP address/LAN/Tailscale),
/// read/write operations gracefully fall back to localStorage/memory instead of throwing
/// "Unsupported operation: FlutterSecureStorageWeb only works in secure contexts".
class SafeStorage {
  final FlutterSecureStorage _secureStorage;
  static final Map<String, String> _memoryFallback = {};

  const SafeStorage([this._secureStorage = const FlutterSecureStorage()]);

  Future<String?> read({required String key}) async {
    try {
      final val = await _secureStorage.read(key: key);
      if (val != null) return val;
    } catch (e) {
      log("SafeStorage read fallback for key '$key': $e");
    }

    final webVal = webStorageGet(key);
    if (webVal != null) return webVal;

    return _memoryFallback[key];
  }

  Future<void> write({required String key, required String value}) async {
    try {
      await _secureStorage.write(key: key, value: value);
    } catch (e) {
      log("SafeStorage write fallback for key '$key': $e");
    }
    webStorageSet(key, value);
    _memoryFallback[key] = value;
  }

  Future<void> delete({required String key}) async {
    try {
      await _secureStorage.delete(key: key);
    } catch (e) {
      log("SafeStorage delete fallback for key '$key': $e");
    }
    webStorageRemove(key);
    _memoryFallback.remove(key);
  }

  Future<void> deleteAll() async {
    try {
      await _secureStorage.deleteAll();
    } catch (e) {
      log("SafeStorage deleteAll fallback: $e");
    }
    webStorageClear();
    _memoryFallback.clear();
  }
}
