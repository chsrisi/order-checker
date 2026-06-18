import 'dart:async';
import 'dart:convert';
import 'dart:developer';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/io.dart';
import 'package:jose/jose.dart';
import 'models.dart';

enum AppView { scanner, orders, finder }

class SecurityService {
  static const _storage = FlutterSecureStorage();

  static const String jwksCacheKey = 'jwks_cache';
  static const String jwksTimestampKey = 'jwks_timestamp';
  static const int jwksTtlMs = 15 * 60 * 1000; // 15 minutes

  static String? _baseUrl;

  static void init(String baseUrl) {
    _baseUrl = baseUrl;
  }

  // 1. Fetching & Caching JWKS
  static Future<JsonWebKeySet> getJwks({bool forceRefresh = false}) async {
    if (_baseUrl == null) {
      throw Exception("SecurityService not initialized with baseUrl");
    }

    if (!forceRefresh) {
      final cachedJwks = await _storage.read(key: jwksCacheKey);
      final cachedTimeStr = await _storage.read(key: jwksTimestampKey);

      if (cachedJwks != null && cachedTimeStr != null) {
        final cachedTime = int.tryParse(cachedTimeStr) ?? 0;
        final now = DateTime.now().millisecondsSinceEpoch;

        if (now - cachedTime < jwksTtlMs) {
          try {
            return JsonWebKeySet.fromJson(jsonDecode(cachedJwks));
          } catch (e) {
            // Log parse fail, fallback to fetch
          }
        }
      }
    }

    // Fetch from server
    final uri = Uri.parse('$_baseUrl/.well-known/jwks.json');
    final response = await http.get(uri).timeout(const Duration(seconds: 10));

    if (response.statusCode == 200) {
      final jwksJson = response.body;
      await _storage.write(key: jwksCacheKey, value: jwksJson);
      await _storage.write(
        key: jwksTimestampKey,
        value: DateTime.now().millisecondsSinceEpoch.toString(),
      );

      return JsonWebKeySet.fromJson(jsonDecode(jwksJson));
    } else {
      throw Exception('Failed to fetch JWKS from server');
    }
  }

  // 2. Clear Cache
  static Future<void> clearJwksCache() async {
    await _storage.delete(key: jwksCacheKey);
    await _storage.delete(key: jwksTimestampKey);
  }

  // 3. Validate JWT
  static Future<bool> isTokenValid(String token) async {
    try {
      final jws = JsonWebSignature.fromCompactSerialization(token);
      var jwks = await getJwks();
      var keyStore = JsonWebKeyStore()..addKeySet(jwks);

      // Attempt verification
      var isValid = await jws.verify(keyStore);

      // If validation fails, force refresh JWKS in case of rotation
      if (!isValid) {
        await clearJwksCache();
        jwks = await getJwks(forceRefresh: true);
        keyStore = JsonWebKeyStore()..addKeySet(jwks);
        isValid = await jws.verify(keyStore);
      }

      if (!isValid) return false;

      // Check expiration manually
      final payload = jws.unverifiedPayload.jsonContent;
      if (payload.containsKey('exp')) {
        final exp = payload['exp'] as int;
        final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
        if (now >= exp) return false;
      }

      return true;
    } catch (e) {
      return false; // Malformed token
    }
  }
}

class AppState extends ChangeNotifier {
  bool _isFetching = false;
  bool _isSaving = false;
  bool _isGlobalLoading = false;
  List<OutboundItem> _outboundItems = [];
  List<WarehouseItem> _foundItems = [];
  List<ShopeeOrder> _orders = [];
  List<PickItemEntry> _pickItemEntries = [];
  List<Stock> _stocks = [];
  final Map<String, List<WarehouseItem>> _findItemsCache = {};
  final Map<String, DateTime> _findItemsCacheTimes = {};
  static const Duration _cacheTtl = Duration(minutes: 5);
  bool _isLoggedIn = false;
  String _username = '';

  void Function(String message, {bool isError, bool isAlert})? onShowMessage;

  final _storage = const FlutterSecureStorage();
  final String _baseUrl = dotenv.env['BASE_URL'] ?? '';
  final String _wsUrl = dotenv.env['WS_URL'] ?? '';

  WebSocketChannel? _channel;
  StreamSubscription? _wsSubscription;
  int _wsRetryCount = 0;
  bool _wsConnectionFailed = false;
  bool _isConnecting = false;

  Completer<String?>? _refreshTokenCompleter;

  // Getters
  bool get isFetching => _isFetching;
  bool get isSaving => _isSaving;
  bool get isGlobalLoading => _isGlobalLoading;
  List<OutboundItem> get outboundItems => _outboundItems;
  List<WarehouseItem> get foundItems => _foundItems;
  List<ShopeeOrder> get orders => _orders;
  List<PickItemEntry> get pickItemEntries => _pickItemEntries;
  List<Stock> get stocks => _stocks;
  bool get isLoggedIn => _isLoggedIn;
  String get username => _username;
  bool get wsConnectionFailed => _wsConnectionFailed;
  String get baseUrl => _baseUrl;

  void initialize() {
    SecurityService.init(_baseUrl);
    checkLoginStatus();
  }

  @override
  void dispose() {
    _closeWebSocket();
    super.dispose();
  }

  void _closeWebSocket() {
    _wsSubscription?.cancel();
    _channel?.sink.close();
    _channel = null;
  }

  Future<void> initWebSocket() async {
    if (_channel != null || _isConnecting) return;
    _isConnecting = true;

    try {
      final response = await fetchWebSocketTicket();
      if (response == null || response.statusCode >= 500) {
        _isConnecting = false;
        _reconnectWebSocket(error: response != null ? "Status ${response.statusCode}" : "Connection error");
        return;
      }
      if (response.statusCode != 200) {
        _isConnecting = false;
        handleLogout(sessionExpired: true);
        onShowMessage?.call(
          "Session expired. Please log in again.",
          isError: true,
        );
        return;
      }

      final data = jsonDecode(response.body);
      final ticket = data['token'] as String?;
      if (ticket == null) {
        _isConnecting = false;
        handleLogout(sessionExpired: true);
        onShowMessage?.call(
          "Session expired. Please log in again.",
          isError: true,
        );
        return;
      }

      final uri = Uri.parse('$_wsUrl/ws?token=$ticket');
      _channel = IOWebSocketChannel.connect(uri);

      _wsSubscription = _channel!.stream.listen(
        (message) {
          if (_wsRetryCount > 0 || _wsConnectionFailed) {
            _wsRetryCount = 0;
            _wsConnectionFailed = false;
            notifyListeners();
          }

          final data = jsonDecode(message);
          final type = data['type'];
          final payload = List<Map<String, dynamic>>.from(data['data']);

          if (type == 'outbound_update') {
            _outboundItems = payload
                .map((i) => OutboundItem.fromJson(i))
                .toList();
          } else if (type == 'shopee_orders_update') {
            _orders = payload.map((i) => ShopeeOrder.fromJson(i)).toList();
          } else if (type == 'pick_item_entries_update') {
            _pickItemEntries = payload
                .map((i) => PickItemEntry.fromJson(i))
                .toList();
          } else if (type == 'stocks_update') {
            _stocks = payload.map((i) => Stock.fromJson(i)).toList();
          }
          notifyListeners();
        },
        onError: (error) {
          log("WebSocket Error: $error");
          _reconnectWebSocket(error: error);
        },
        onDone: () {
          log("WebSocket Done");
          _reconnectWebSocket();
        },
      );
    } catch (e) {
      log("WebSocket Init Error: $e");
      _reconnectWebSocket(error: e);
    } finally {
      _isConnecting = false;
    }
  }

  void _reconnectWebSocket({dynamic error}) async {
    _closeWebSocket();

    if (error != null && error.toString().contains('403')) {
      log("WebSocket: 403 detected, attempting token refresh...");
      final newToken = await performRefresh();
      if (newToken != null) {
        log("WebSocket: Token refreshed, re-initializing...");
        initWebSocket();
      } else {
        log("WebSocket: Token refresh failed after 403. Logging out...");
        handleLogout(sessionExpired: true);
        onShowMessage?.call(
          "Session expired. Please log in again.",
          isError: true,
        );
      }
      return;
    }

    _wsRetryCount++;
    if (_wsRetryCount > 5) {
      log("WebSocket: max retries exceeded, stopping.");
      _wsConnectionFailed = true;
      notifyListeners();
      onShowMessage?.call(
        "WebSocket connection failed after multiple retries.",
        isError: true,
      );
      return;
    }
    log("WebSocket: retry attempt $_wsRetryCount/5");
    Future.delayed(const Duration(seconds: 2), () {
      if (_isLoggedIn) {
        initWebSocket();
      }
    });
    notifyListeners();
  }

  void retryWebSocket() {
    initWebSocket();
  }

  Future<void> checkLoginStatus() async {
    final accessToken = await _storage.read(key: 'access_token');
    if (accessToken == null) return;

    _username = await _storage.read(key: 'username') ?? '';

    if (!await SecurityService.isTokenValid(accessToken)) {
      final newToken = await performRefresh();
      if (newToken != null) {
        _isLoggedIn = true;
        initWebSocket();
        fetchHistory();
      }
    } else {
      _isLoggedIn = true;
      initWebSocket();
      fetchHistory();
    }
    notifyListeners();
  }

  Future<String?> performRefresh() async {
    if (_refreshTokenCompleter != null) {
      return await _refreshTokenCompleter!.future;
    }

    _refreshTokenCompleter = Completer<String?>();
    try {
      final refreshToken = await _storage.read(key: 'refresh_token');
      if (refreshToken == null) {
        handleLogout(sessionExpired: false);
        _refreshTokenCompleter!.complete(null);
        return null;
      }

      final refreshResp = await makeRequest(
        '$_baseUrl/auth/refresh',
        method: 'POST',
        body: {'refresh_token': refreshToken},
        requiresAuth: false,
      );

      if (refreshResp?.statusCode == 200) {
        final data = jsonDecode(refreshResp!.body);
        await _storage.write(key: 'access_token', value: data['access_token']);
        await _storage.write(
          key: 'refresh_token',
          value: data['refresh_token'],
        );

        final newToken = data['access_token'];
        _refreshTokenCompleter!.complete(newToken);
        return newToken;
      } else {
        await handleLogout(sessionExpired: true);
        onShowMessage?.call(
          "Session expired. Please log in again.",
          isError: true,
        );
        _refreshTokenCompleter!.complete(null);
        return null;
      }
    } catch (e) {
      _refreshTokenCompleter!.complete(null);
      return null;
    } finally {
      _refreshTokenCompleter = null;
    }
  }

  Future<http.Response?> fetchWebSocketTicket() async {
    return await makeRequest(
      '$_baseUrl/auth/ws-token',
      method: 'POST',
      requiresAuth: true,
    );
  }

  Future<http.Response?> makeRequest(
    String url, {
    String method = 'GET',
    Map<String, dynamic>? body,
    bool requiresAuth = true,
  }) async {
    _isGlobalLoading = true;
    notifyListeners();
    try {
      Future<http.Response> doRequest(String? token) async {
        final uri = Uri.parse(url);
        final payload = body != null ? jsonEncode(body) : null;

        final headers = <String, String>{'Content-Type': 'application/json'};

        if (requiresAuth && token != null) {
          headers['Authorization'] = 'Bearer $token';
        }

        http.Response response;
        if (method == 'POST') {
          response = await http.post(uri, headers: headers, body: payload);
        } else if (method == 'DELETE') {
          response = await http.delete(uri, headers: headers, body: payload);
        } else {
          response = await http.get(uri, headers: headers);
        }

        return response;
      }

      String? accessToken = requiresAuth
          ? await _storage.read(key: 'access_token')
          : null;
      if (requiresAuth && accessToken == null) return null;

      final timeoutWarning = Timer(const Duration(seconds: 5), () {
        onShowMessage?.call("Request taking longer than expected...");
      });

      var response = await doRequest(
        accessToken,
      ).timeout(const Duration(seconds: 15));
      log("${response.statusCode} - ${response.body}");
      timeoutWarning.cancel();

      if (response.statusCode >= 500) {
        onShowMessage?.call("Server error occurred.", isError: true);
      }

      if (response.statusCode == 409) {
        String msg = "Duplicate scan detected.";
        try {
          final data = jsonDecode(response.body);
          if (data is Map && data['detail'] != null) {
            msg = data['detail'].toString();
          }
        } catch (_) {}
        onShowMessage?.call(msg, isError: true, isAlert: true);
      }

      if (requiresAuth && response.statusCode == 401) {
        final newToken = await performRefresh();
        if (newToken != null) {
          final retryTimeoutWarning = Timer(const Duration(seconds: 2), () {
            onShowMessage?.call("Retry taking longer than expected...");
          });
          final retryResponse = await doRequest(
            newToken,
          ).timeout(const Duration(seconds: 15));
          retryTimeoutWarning.cancel();
          if (retryResponse.statusCode >= 500) {
            onShowMessage?.call("Server error occurred.", isError: true);
          }
          return retryResponse;
        } else {
          return response;
        }
      }
      return response;
    } catch (e) {
      log("Request Error: $e");
      if (e is TimeoutException) {
        onShowMessage?.call("Request timed out.", isError: true);
      }
      return null;
    } finally {
      _isGlobalLoading = false;
      notifyListeners();
    }
  }

  Future<void> handleLogout({bool sessionExpired = false}) async {
    final refreshToken = await _storage.read(key: 'refresh_token');
    if (refreshToken != null) {
      await makeRequest(
        '$_baseUrl/auth/logout',
        method: 'POST',
        body: {'refresh_token': refreshToken},
        requiresAuth: false,
      );
    }
    await _storage.deleteAll();
    _isLoggedIn = false;
    _username = '';
    _outboundItems = [];
    _foundItems = [];
    _stocks = [];
    _findItemsCache.clear();
    _findItemsCacheTimes.clear();
    _closeWebSocket();
    notifyListeners();
  }

  Future<bool> login(String username, String password) async {
    if (username.isEmpty || password.isEmpty) return false;

    _isFetching = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/auth/login',
        method: 'POST',
        body: {'username': username, 'password': password},
        requiresAuth: false,
      );

      if (response?.statusCode == 200) {
        final data = jsonDecode(response!.body);
        await _storage.write(key: 'access_token', value: data['access_token']);
        await _storage.write(
          key: 'refresh_token',
          value: data['refresh_token'],
        );
        await _storage.write(key: 'username', value: username);

        _isLoggedIn = true;
        _username = username;
        fetchHistory();
        notifyListeners();
        return true;
      } else {
        return false;
      }
    } catch (e) {
      log("Login Error: $e");
      onShowMessage?.call("An error occurred during login.", isError: true);
      return false;
    } finally {
      _isFetching = false;
      notifyListeners();
    }
  }

  Future<bool> register(String username, String password) async {
    if (username.isEmpty || password.isEmpty) return false;

    _isFetching = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/auth/register',
        method: 'POST',
        body: {'username': username, 'password': password},
        requiresAuth: false,
      );

      if (response?.statusCode == 200) {
        final data = jsonDecode(response!.body);
        await _storage.write(key: 'access_token', value: data['access_token']);
        await _storage.write(
          key: 'refresh_token',
          value: data['refresh_token'],
        );
        await _storage.write(key: 'username', value: username);

        _isLoggedIn = true;
        _username = username;
        fetchHistory();
        notifyListeners();
        return true;
      } else {
        return false;
      }
    } catch (e) {
      log("Register Error: $e");
      onShowMessage?.call(
        "An error occurred during registration.",
        isError: true,
      );
      return false;
    } finally {
      _isFetching = false;
      notifyListeners();
    }
  }

  Future<void> postOutbound(String content, {List<String>? tags}) async {
    if (content.isEmpty) return;

    _isSaving = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/outbound',
        method: 'POST',
        body: {'content': content, 'tags': tags},
      );

      if (response?.statusCode == 200) {
        fetchHistory();
        onShowMessage?.call("Item saved successfully.");
      } else {
        onShowMessage?.call("Failed to save item.", isError: true);
      }
    } catch (e) {
      log("Save Error: $e");
      onShowMessage?.call("An error occurred while saving.", isError: true);
    } finally {
      _isSaving = false;
      notifyListeners();
    }
  }

  Future<void> postScanEntry(String sku, int qty, {String? orderSn}) async {
    _isSaving = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/pick-item',
        method: 'POST',
        body: {'sku': sku, 'qty': qty, 'order_sn': ?orderSn},
      );

      if (response?.statusCode == 200) {
        onShowMessage?.call("Scan entry posted.");
      } else {
        onShowMessage?.call("Failed to post scan entry.", isError: true);
      }
    } catch (e) {
      log("Scan Error: $e");
      onShowMessage?.call(
        "An error occurred during scan submission.",
        isError: true,
      );
    } finally {
      _isSaving = false;
      notifyListeners();
    }
  }

  Future<int?> acquireOrder(String orderSn) async {
    if (orderSn.isEmpty) return null;

    _isSaving = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/shopee/orders/acquire?order_sn=$orderSn',
        method: 'POST',
      );
      if (response?.statusCode == 200) {
        onShowMessage?.call("Order acquired successfully.");
        return 200;
      } else if (response?.statusCode == 404) {
        return 404;
      } else {
        onShowMessage?.call("Failed to acquire order.", isError: true);
        return response?.statusCode;
      }
    } catch (e) {
      log("Acquire Order Error: $e");
      onShowMessage?.call(
        "An error occurred while acquiring order.",
        isError: true,
      );
      return null;
    } finally {
      _isSaving = false;
      notifyListeners();
    }
  }

  Future<bool> refreshShopeeOrders() async {
    try {
      final response = await makeRequest(
        '$_baseUrl/shopee/orders?refresh=true',
        method: 'GET',
      );
      return response?.statusCode == 200;
    } catch (e) {
      log("Refresh Shopee Orders Error: $e");
      return false;
    }
  }

  Future<void> fetchHistory() async {
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_items'}));
  }

  Future<void> fetchOrdersData() async {
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_shopee_orders'}));
  }

  Future<void> fetchStocksData() async {
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_stocks'}));
  }

  Future<void> searchItems(String query) async {
    if (query.isEmpty) return;

    final normalizedQuery = query.trim().toLowerCase();
    final cachedTime = _findItemsCacheTimes[normalizedQuery];
    if (_findItemsCache.containsKey(normalizedQuery) &&
        cachedTime != null &&
        DateTime.now().difference(cachedTime) < _cacheTtl) {
      _foundItems = _findItemsCache[normalizedQuery]!;
      if (_foundItems.isEmpty) {
        onShowMessage?.call("No items found.");
      }
      notifyListeners();
      return;
    }

    _isFetching = true;
    notifyListeners();
    try {
      final response = await makeRequest('$_baseUrl/items/find?query=$query');
      if (response?.statusCode == 200) {
        final List<WarehouseItem> results = (jsonDecode(response!.body) as List)
            .map((i) => WarehouseItem.fromJson(i))
            .toList();

        _findItemsCache[normalizedQuery] = results;
        _findItemsCacheTimes[normalizedQuery] = DateTime.now();

        _foundItems = results;
        if (_foundItems.isEmpty) {
          onShowMessage?.call("No items found.");
        }
      } else {
        onShowMessage?.call("Search failed.", isError: true);
      }
    } catch (e) {
      log("Search Error: $e");
      onShowMessage?.call("An error occurred during search.", isError: true);
    } finally {
      _isFetching = false;
      notifyListeners();
    }
  }

  Future<void> deleteScanEntry(int id) async {
    try {
      String url = '$_baseUrl/pick-item?entry_id=$id';

      final response = await makeRequest(url, method: 'DELETE');
      if (response?.statusCode == 200) {
        onShowMessage?.call("Scan entry deleted.");
      } else {
        onShowMessage?.call("Failed to delete scan entry.", isError: true);
      }
    } catch (e) {
      log("Delete Scan Entry Error: $e");
      onShowMessage?.call("An error occurred while deleting.", isError: true);
    }
  }

  Future<void> assignToLabel(
    int entryId,
    String orderSn, {
    int? qty,
    int? orderItemQty,
  }) async {
    try {
      String url =
          '$_baseUrl/pick-item/assign?entry_id=$entryId&order_sn=$orderSn';
      if (qty != null) {
        url += '&qty=$qty';
      }
      final response = await makeRequest(url, method: 'POST');
      if (response?.statusCode == 200) {
        if (qty != null && orderItemQty != null && qty > orderItemQty) {
          onShowMessage?.call(
            "Assigned to label, but qty ($qty) exceeds order requirement ($orderItemQty).",
            isAlert: true,
          );
        } else {
          onShowMessage?.call("Assigned to label.");
        }
      } else {
        onShowMessage?.call("Failed to assign to label.", isError: true);
      }
    } catch (e) {
      log("Assign Error: $e");
      onShowMessage?.call("An error occurred while assigning.", isError: true);
    }
  }

  Future<void> unassignSku(String orderSn, String sku, int qty) async {
    _isSaving = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/pick-item/unassign?order_sn=$orderSn&sku=$sku&qty=$qty',
        method: 'POST',
      );
      if (response?.statusCode == 200) {
        onShowMessage?.call("SKU unassigned successfully.");
      } else {
        onShowMessage?.call("Failed to unassign SKU.", isError: true);
      }
    } catch (e) {
      log("Unassign Error: $e");
      onShowMessage?.call(
        "An error occurred while unassigning.",
        isError: true,
      );
    } finally {
      _isSaving = false;
      notifyListeners();
    }
  }

  Future<void> fetchStocks() async {
    await fetchStocksData();
  }

  Future<void> updateStock(
    String idbrng,
    int qty, {
    String mode = "set",
    String? location,
    String? moveTo,
  }) async {
    _isSaving = true;
    notifyListeners();
    try {
      final body = {
        'sku': idbrng,
        'stock': qty,
        'mode': mode,
        if (location != null) 'location': location,
        if (moveTo != null) 'move_to': moveTo,
      };
      final response = await makeRequest(
        '$_baseUrl/stocks',
        method: 'POST',
        body: body,
      );
      if (response?.statusCode == 200) {
        await fetchStocks();
        onShowMessage?.call("Stock updated.");
      } else {
        onShowMessage?.call("Failed to update stock.", isError: true);
      }
    } finally {
      _isSaving = false;
      notifyListeners();
    }
  }

  String? parseSupplierBarcode(String input) {
    final lines = input.split('\n');
    if (lines.isEmpty) return null;
    var firstLine = lines[0].trim();
    if (firstLine.isEmpty) return null;

    if (firstLine.contains(' ')) {
      firstLine = firstLine.split(' ')[0].trim();
    }

    final cleaned = firstLine;

    // 3 segments: {batch}-{type}-{id} where id is numeric
    final regExp3 = RegExp(r'^([a-zA-Z0-9]+)-([a-zA-Z0-9]+)-([0-9]+)$');
    final match3 = regExp3.firstMatch(cleaned);
    if (match3 != null) {
      final type = match3.group(2);
      final id = match3.group(3);
      if (type != null && id != null) {
        return "$type-$id";
      }
    }

    // 2 segments: {batch}-{id} where id is numeric
    final regExp2 = RegExp(r'^([a-zA-Z0-9]+)-([0-9]+)$');
    final match2 = regExp2.firstMatch(cleaned);
    if (match2 != null) {
      final id = match2.group(2);
      if (id != null) {
        return id;
      }
    }

    return null;
  }

  Future<String?> resolveSupplierBarcode(String barcode) async {
    try {
      final response = await makeRequest(
        '$_baseUrl/items/resolve-supplier-barcode?barcode=${Uri.encodeComponent(barcode)}',
      );
      if (response?.statusCode == 200) {
        final data = jsonDecode(response!.body);
        return data['sku'] as String?;
      }
    } catch (e) {
      log("Resolve Barcode Error: $e");
    }
    return null;
  }
}
