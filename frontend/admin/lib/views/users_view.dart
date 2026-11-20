import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';

class UsersView extends StatelessWidget {
  const UsersView({super.key});

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    final users = appState.registeredUsers;

    Widget body;
    if (appState.isLoading && users.isEmpty) {
      body = const Center(child: CircularProgressIndicator());
    } else if (users.isEmpty) {
      body = const Center(child: Text("No registered users"));
    } else {
      body = RefreshIndicator(
        onRefresh: appState.fetchUsers,
        child: ListView.builder(
          itemCount: users.length,
          itemBuilder: (context, index) {
            final user = users[index];
            final isAdmin = user.role == 'admin';
            return ListTile(
              leading: const CircleAvatar(child: Icon(Icons.person)),
              title: Text(user.username),
              subtitle: Text("Role: ${user.role}"),
              trailing: isAdmin
                  ? null
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          tooltip: 'Reset password',
                          icon: const Icon(Icons.lock_reset),
                          onPressed: () =>
                              _resetPassword(context, appState, user.username),
                        ),
                        IconButton(
                          tooltip: 'Delete user',
                          icon: const Icon(
                            Icons.delete_outline,
                            color: Colors.red,
                          ),
                          onPressed: () => _confirmDeleteUser(
                            context,
                            appState,
                            user.username,
                          ),
                        ),
                      ],
                    ),
            );
          },
        ),
      );
    }

    return Stack(
      children: [
        Positioned.fill(child: body),
        Positioned(
          right: 16,
          bottom: 16,
          child: FloatingActionButton.extended(
            heroTag: 'create-user',
            icon: const Icon(Icons.person_add),
            label: const Text('New operator'),
            onPressed: () => _createUser(context, appState),
          ),
        ),
      ],
    );
  }

  Future<void> _createUser(BuildContext context, AppState appState) async {
    final result = await showDialog<(String, String)>(
      context: context,
      builder: (context) => const _CredentialsDialog(
        title: 'New operator',
        askUsername: true,
        confirmLabel: 'Create',
      ),
    );
    if (result == null) return;
    final error = await appState.createUser(result.$1, result.$2);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(error ?? 'Operator ${result.$1} created')),
    );
  }

  Future<void> _resetPassword(
    BuildContext context,
    AppState appState,
    String username,
  ) async {
    final result = await showDialog<(String, String)>(
      context: context,
      builder: (context) => _CredentialsDialog(
        title: 'Reset password for $username',
        askUsername: false,
        confirmLabel: 'Reset',
        note: 'All of this user\'s devices will be logged out.',
      ),
    );
    if (result == null) return;
    final error = await appState.resetUserPassword(username, result.$2);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(error ?? 'Password reset for $username')),
    );
  }

  Future<void> _confirmDeleteUser(
    BuildContext context,
    AppState appState,
    String username,
  ) async {
    final bool? confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("Delete User"),
        content: const Text(
          "This will delete the user and all their scans. Are you sure?",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text("Delete"),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    final success = await appState.deleteUser(username);
    if (!context.mounted) return;
    if (success) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('User deleted')));
    }
  }
}

/// Returns (username, password); username is empty when [askUsername] is false.
class _CredentialsDialog extends StatefulWidget {
  const _CredentialsDialog({
    required this.title,
    required this.askUsername,
    required this.confirmLabel,
    this.note,
  });

  final String title;
  final bool askUsername;
  final String confirmLabel;
  final String? note;

  @override
  State<_CredentialsDialog> createState() => _CredentialsDialogState();
}

class _CredentialsDialogState extends State<_CredentialsDialog> {
  final _formKey = GlobalKey<FormState>();
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _obscure = true;

  static final _usernamePattern = RegExp(r'^[a-zA-Z0-9_]+$');

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    Navigator.pop(context, (_username.text.trim(), _password.text));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (widget.note != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(widget.note!),
              ),
            if (widget.askUsername)
              TextFormField(
                controller: _username,
                autofocus: true,
                decoration: const InputDecoration(labelText: 'Username'),
                validator: (v) {
                  final value = (v ?? '').trim();
                  if (value.isEmpty) return 'Required';
                  if (value.length > 64) return 'At most 64 characters';
                  if (!_usernamePattern.hasMatch(value)) {
                    return 'Letters, digits and underscores only';
                  }
                  return null;
                },
              ),
            TextFormField(
              controller: _password,
              autofocus: !widget.askUsername,
              obscureText: _obscure,
              decoration: InputDecoration(
                labelText: 'Password',
                suffixIcon: IconButton(
                  icon: Icon(
                    _obscure ? Icons.visibility : Icons.visibility_off,
                  ),
                  onPressed: () => setState(() => _obscure = !_obscure),
                ),
              ),
              validator: (v) {
                final value = v ?? '';
                if (value.isEmpty) return 'Required';
                if (value.length > 256) return 'At most 256 characters';
                return null;
              },
            ),
            TextFormField(
              controller: _confirm,
              obscureText: _obscure,
              decoration: const InputDecoration(labelText: 'Confirm password'),
              validator: (v) =>
                  v == _password.text ? null : 'Passwords do not match',
              onFieldSubmitted: (_) => _submit(),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(onPressed: _submit, child: Text(widget.confirmLabel)),
      ],
    );
  }
}
