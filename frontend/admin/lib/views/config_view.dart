import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class ConfigView extends StatefulWidget {
  const ConfigView({super.key});

  @override
  State<ConfigView> createState() => _ConfigViewState();
}

class _ConfigViewState extends State<ConfigView> {
  final _formKey = GlobalKey<FormState>();
  final _unlockFormKey = GlobalKey<FormState>();

  late TextEditingController _accessTokenController;
  late TextEditingController _refreshTokenController;
  late TextEditingController _passwordController;

  String? _unlockError;

  @override
  void initState() {
    super.initState();
    final appState = Provider.of<AppState>(context, listen: false);
    _accessTokenController = TextEditingController(text: appState.shopeeAccessToken);
    _refreshTokenController = TextEditingController(text: appState.shopeeRefreshToken);
    _passwordController = TextEditingController();
  }

  @override
  void dispose() {
    _accessTokenController.dispose();
    _refreshTokenController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appState = context.watch<AppState>();
    final theme = Theme.of(context);

    // If locked, show password prompt
    if (!appState.isConfigUnlocked) {
      return Center(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 400),
          padding: const EdgeInsets.all(16.0),
          child: Card(
            elevation: 8,
            shadowColor: Colors.black26,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(color: Colors.red.shade100, width: 1.5),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 32.0),
              child: Form(
                key: _unlockFormKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircleAvatar(
                      radius: 36,
                      backgroundColor: Colors.red.shade50,
                      child: Icon(
                        Icons.lock_outline,
                        color: theme.colorScheme.primary,
                        size: 36,
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      "Secure Settings",
                      style: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      "Please verify your administrator password to access the Shopee credentials configuration.",
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey, fontSize: 13),
                    ),
                    const SizedBox(height: 24),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: true,
                      autofocus: true,
                      decoration: InputDecoration(
                        labelText: "Password",
                        prefixIcon: const Icon(Icons.password_outlined),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                        errorText: _unlockError,
                      ),
                      validator: (value) {
                        if (value == null || value.isEmpty) {
                          return "Password is required";
                        }
                        return null;
                      },
                      onFieldSubmitted: (_) => _handleUnlock(appState),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: FilledButton.icon(
                        icon: appState.isLoading
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  color: Colors.white,
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.lock_open),
                        label: const Text(
                          "Unlock Config",
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                        style: FilledButton.styleFrom(
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                        ),
                        onPressed: appState.isLoading ? null : () => _handleUnlock(appState),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }

    // Update text controllers if they are empty and we just loaded data
    if (_accessTokenController.text.isEmpty && appState.shopeeAccessToken.isNotEmpty) {
      _accessTokenController.text = appState.shopeeAccessToken;
    }
    if (_refreshTokenController.text.isEmpty && appState.shopeeRefreshToken.isNotEmpty) {
      _refreshTokenController.text = appState.shopeeRefreshToken;
    }

    return Scaffold(
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Center(
          child: Container(
            constraints: const BoxConstraints(maxWidth: 600),
            child: Card(
              elevation: 4,
              shadowColor: Colors.black12,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
                side: BorderSide(color: Colors.red.shade100, width: 1),
              ),
              child: Padding(
                padding: const EdgeInsets.all(32.0),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Row(
                            children: [
                              Icon(Icons.settings, color: theme.colorScheme.primary, size: 28),
                              const SizedBox(width: 12),
                              Text(
                                "Shopee API Config",
                                style: theme.textTheme.titleLarge?.copyWith(
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ],
                          ),
                          IconButton(
                            icon: const Icon(Icons.lock, color: Colors.grey),
                            tooltip: "Lock View",
                            onPressed: () => appState.lockShopeeConfig(),
                          ),
                        ],
                      ),
                      const Divider(height: 32),
                      
                      // Current IP Display Box
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                        decoration: BoxDecoration(
                          color: appState.shopeeCurrentIp == 'unknown' 
                              ? Colors.grey.shade100 
                              : Colors.red.shade50,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                            color: appState.shopeeCurrentIp == 'unknown'
                                ? Colors.grey.shade300
                                : Colors.red.shade200,
                          ),
                        ),
                        child: Row(
                          children: [
                            Icon(
                              appState.shopeeCurrentIp == 'unknown'
                                  ? Icons.info_outline
                                  : Icons.warning_amber_rounded,
                              color: appState.shopeeCurrentIp == 'unknown'
                                  ? Colors.grey.shade700
                                  : Colors.red.shade700,
                              size: 20,
                            ),
                            const SizedBox(width: 12),
                            Text(
                              "Current IP: ",
                              style: TextStyle(
                                fontWeight: FontWeight.bold,
                                color: appState.shopeeCurrentIp == 'unknown'
                                    ? Colors.grey.shade800
                                    : Colors.red.shade900,
                              ),
                            ),
                            Text(
                              appState.shopeeCurrentIp,
                              style: TextStyle(
                                fontFamily: 'monospace',
                                fontWeight: FontWeight.bold,
                                color: appState.shopeeCurrentIp == 'unknown'
                                    ? Colors.grey.shade800
                                    : Colors.red.shade900,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 24),
                      
                      // Access Token Box
                      Text(
                        "Access Token",
                        style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      TextFormField(
                        controller: _accessTokenController,
                        maxLines: 2,
                        decoration: InputDecoration(
                          hintText: "Enter manual Shopee access token...",
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                            borderSide: BorderSide(color: theme.colorScheme.primary, width: 2),
                          ),
                        ),
                        validator: (value) {
                          if (value == null || value.trim().isEmpty) {
                            return 'Access token cannot be empty';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 20),
                      
                      // Refresh Token Box
                      Text(
                        "Refresh Token",
                        style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      TextFormField(
                        controller: _refreshTokenController,
                        maxLines: 2,
                        decoration: InputDecoration(
                          hintText: "Enter manual Shopee refresh token...",
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                            borderSide: BorderSide(color: theme.colorScheme.primary, width: 2),
                          ),
                        ),
                        validator: (value) {
                          if (value == null || value.trim().isEmpty) {
                            return 'Refresh token cannot be empty';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 32),
                      
                      // Save Button
                      SizedBox(
                        width: double.infinity,
                        height: 48,
                        child: FilledButton.icon(
                          icon: appState.isLoading
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(
                                    color: Colors.white,
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.save),
                          label: const Text(
                            "Save Configuration",
                            style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                          style: FilledButton.styleFrom(
                            backgroundColor: theme.colorScheme.primary,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          onPressed: appState.isLoading
                              ? null
                              : () => _handleSave(context, appState),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _handleUnlock(AppState appState) async {
    if (!_unlockFormKey.currentState!.validate()) return;
    setState(() {
      _unlockError = null;
    });

    final success = await appState.unlockShopeeConfig(_passwordController.text);
    if (!mounted) return;

    if (success) {
      _passwordController.clear();
      appState.fetchShopeeConfig();
    } else {
      setState(() {
        _unlockError = "Incorrect password or authorization error";
      });
    }
  }

  Future<void> _handleSave(BuildContext context, AppState appState) async {
    if (!_formKey.currentState!.validate()) return;

    final success = await appState.saveShopeeConfig(
      _accessTokenController.text.trim(),
      _refreshTokenController.text.trim(),
    );

    if (!context.mounted) return;

    if (success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Shopee configuration saved successfully!"),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      // Check if unlocked state was reset (meaning token expired)
      if (!appState.isConfigUnlocked) {
        _showSessionExpiredDialog(context);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Failed to save configuration. Please try again."),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  void _showSessionExpiredDialog(BuildContext context) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text("Session Expired"),
        content: const Text(
          "Your secure access session has expired. "
          "Please re-enter your password to save the changes.",
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              // Re-trigger build which will show the unlock screen
              setState(() {});
            },
            child: const Text("OK"),
          ),
        ],
      ),
    );
  }
}
