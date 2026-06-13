import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';
import '../models.dart';

class ScannerScreen extends StatefulWidget {
  const ScannerScreen({super.key});

  @override
  State<ScannerScreen> createState() => _ScannerScreenState();
}

class _ScannerScreenState extends State<ScannerScreen> {
  final TextEditingController _scanController = TextEditingController();
  final FocusNode _scanFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final appState = Provider.of<AppState>(context, listen: false);
      appState.onShowMessage = (message, {isError = false, isAlert = false}) {
        if (!mounted) return;
        if (isAlert) {
          showDialog(
            context: context,
            builder: (context) => AlertDialog(
              title: Text(isError ? "Error / Duplicate" : "Notification"),
              content: Text(message),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text("OK"),
                ),
              ],
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(message),
              backgroundColor: isError ? Colors.red : null,
            ),
          );
        }
      };
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        final appState = Provider.of<AppState>(context, listen: false);
        appState.onShowMessage = null;
      }
    });
    _scanController.dispose();
    _scanFocusNode.dispose();
    super.dispose();
  }

  void _handleSubmit(BuildContext context, AppState appState) {
    appState.postOutbound(_scanController.text.trim());
    _scanController.clear();
    _scanFocusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: <Widget>[
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.center_focus_weak, size: 40, color: Colors.blue),
              const SizedBox(width: 16),
              const Text(
                "Scan Item",
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _scanController,
            focusNode: _scanFocusNode,
            decoration: InputDecoration(
              hintText: "Scan result...",
              border: const OutlineInputBorder(),
              suffixIcon: IconButton(
                icon: const Icon(Icons.clear),
                onPressed: () => _scanController.clear(),
              ),
            ),
            onSubmitted: (_) => _handleSubmit(context, appState),
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: appState.isSaving
                  ? null
                  : () => _handleSubmit(context, appState),
              icon: appState.isSaving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send),
              label: const Text("Submit Scan"),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.blue,
                foregroundColor: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class ScannerHistory extends StatefulWidget {
  const ScannerHistory({super.key});

  @override
  State<ScannerHistory> createState() => _ScannerHistoryState();
}

class _ScannerHistoryState extends State<ScannerHistory> {
  String? _filterTag;

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);

    List<OutboundItem> filteredItems = appState.outboundItems;

    if (_filterTag != null) {
      filteredItems = filteredItems
          .where((item) => item.tags.contains(_filterTag))
          .toList();
    }

    final scannerTags = appState.outboundItems
        .expand((item) => item.tags)
        .toSet()
        .toList();

    return Column(
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 16.0),
          child: Row(
            children: [
              ChoiceChip(
                label: const Text("All"),
                selected: _filterTag == null,
                onSelected: (selected) {
                  if (selected) {
                    setState(() {
                      _filterTag = null;
                    });
                  }
                },
              ),
              const SizedBox(width: 8),
              ...scannerTags.map((tag) {
                return Padding(
                  padding: const EdgeInsets.only(right: 8.0),
                  child: ChoiceChip(
                    label: Text(tag),
                    selected: _filterTag == tag,
                    onSelected: (selected) {
                      setState(() {
                        _filterTag = selected ? tag : null;
                      });
                    },
                  ),
                );
              }),
            ],
          ),
        ),
        Expanded(
          child: filteredItems.isEmpty
              ? const Center(child: Text("No items scanned yet"))
              : ListView.builder(
                  itemCount: filteredItems.length,
                  itemBuilder: (context, index) {
                    final item = filteredItems[index];
                    final DateTime date = item.createdAt.toLocal();
                    return ListTile(
                      leading: const CircleAvatar(
                        child: Icon(Icons.receipt_long),
                      ),
                      title: Row(
                        children: [
                          Expanded(
                            child: Text(
                              item.content,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          Wrap(
                            spacing: 4,
                            children: item.tags.map((tag) => Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.blue.shade100,
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Text(
                                tag,
                                style: TextStyle(
                                  fontSize: 10,
                                  color: Colors.blue.shade900,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            )).toList(),
                          ),
                        ],
                      ),
                      subtitle: Text(
                        "Scanned at: ${date.hour}:${date.minute.toString().padLeft(2, '0')} - ${date.day}/${date.month}",
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class ScannerView extends StatelessWidget {
  final int subIndex;
  const ScannerView({super.key, required this.subIndex});

  @override
  Widget build(BuildContext context) {
    switch (subIndex) {
      case 0:
        return const ScannerScreen();
      case 1:
        return const ScannerHistory();
      default:
        return const Center(child: Text("Page not found"));
    }
  }
}
